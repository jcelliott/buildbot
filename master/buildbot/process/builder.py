# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import random, weakref
from zope.interface import implements
from twisted.python import log, failure
from twisted.spread import pb
from twisted.application import service, internet
from twisted.internet import defer

from buildbot import interfaces, config
from buildbot.status.progress import Expectations
from buildbot.status.builder import RETRY
from buildbot.status.buildrequest import BuildRequestStatus
from buildbot.process.properties import Properties
from buildbot.process import buildrequest, slavebuilder
from buildbot.process.slavebuilder import BUILDING

from buildbot.db import buildrequests
import sys

class Builder(config.ReconfigurableServiceMixin,
              pb.Referenceable,
              service.MultiService):

    # reconfigure builders before slaves
    reconfig_priority = 196

    def __init__(self, name, _addServices=True):
        service.MultiService.__init__(self)
        self.name = name

        # this is created the first time we get a good build
        self.expectations = None

        # build/wannabuild slots: Build objects move along this sequence
        self.building = []
        # old_building holds active builds that were stolen from a predecessor
        self.old_building = weakref.WeakKeyDictionary()

        # buildslaves which have connected but which are not yet available.
        # These are always in the ATTACHING state.
        self.attaching_slaves = []

        # buildslaves at our disposal. Each SlaveBuilder instance has a
        # .state that is IDLE, PINGING, or BUILDING. "PINGING" is used when a
        # Build is about to start, to make sure that they're still alive.
        self.slaves = []

        self.config = None
        self.builder_status = None

        if _addServices:
            self.reclaim_svc = internet.TimerService(10*60,
                                            self.reclaimAllBuilds)
            self.reclaim_svc.setServiceParent(self)

            # update big status every 30 minutes, working around #1980
            self.updateStatusService = internet.TimerService(30*60,
                                            self.updateBigStatus)
            self.updateStatusService.setServiceParent(self)

    def reconfigService(self, new_config):
        # find this builder in the config
        for builder_config in new_config.builders:
            if builder_config.name == self.name:
                break
        else:
            assert 0, "no config found for builder '%s'" % self.name

        # set up a builder status object on the first reconfig
        if not self.builder_status:
            self.builder_status = self.master.status.builderAdded(
                    builder_config.name,
                    builder_config.builddir,
                    builder_config.category, builder_config.friendly_name)

        self.config = builder_config

        self.builder_status.setCategory(builder_config.category)
        self.builder_status.setSlavenames(self.config.slavenames)
        self.builder_status.setCacheSize(new_config.caches['Builds'])
        self.builder_status.setProject(builder_config.project)
        self.builder_status.setFriendlyName(builder_config.friendly_name)
        self.builder_status.setTags(builder_config.tags)

        return defer.succeed(None)

    def stopService(self):
        d = defer.maybeDeferred(lambda :
                service.MultiService.stopService(self))
        def flushMaybeStartBuilds(_):
            # at this point, self.running = False, so another maybeStartBuild
            # invocation won't hurt anything, but it also will not complete
            # until any currently-running invocations are done, so we know that
            # the builder is quiescent at that time.
            return self.maybeStartBuild()
        d.addCallback(flushMaybeStartBuilds)
        return d

    def __repr__(self):
        return "<Builder '%r' at %d>" % (self.name, id(self))

    @defer.inlineCallbacks
    def getOldestRequestTime(self):

        """Returns the submitted_at of the oldest unclaimed build request for
        this builder, or None if there are no build requests.

        @returns: datetime instance or None, via Deferred
        """
        unclaimed = yield self.master.db.buildrequests.getBuildRequests(
                        buildername=self.name, claimed=False)

        if unclaimed:
            unclaimed = [ brd['submitted_at'] for brd in unclaimed ]
            unclaimed.sort()
            defer.returnValue(unclaimed[0])
        else:
            defer.returnValue(None)

    def reclaimAllBuilds(self):
        brids = set()
        for b in self.building:
            brids.update([br.id for br in b.requests])
        for b in self.old_building:
            brids.update([br.id for br in b.requests])

        if not brids:
            return defer.succeed(None)

        d = self.master.db.buildrequests.reclaimBuildRequests(brids)
        d.addErrback(log.err, 'while re-claiming running BuildRequests')
        return d

    def getBuild(self, number):
        for b in self.building:
            if b.build_status and b.build_status.number == number:
                return b
        for b in self.old_building.keys():
            if b.build_status and b.build_status.number == number:
                return b
        return None

    def addLatentSlave(self, slave):
        assert interfaces.ILatentBuildSlave.providedBy(slave)
        for s in self.slaves:
            if s == slave:
                break
        else:
            sb = slavebuilder.LatentSlaveBuilder(slave, self)
            self.builder_status.addPointEvent(
                ['added', 'latent', slave.slavename])
            self.slaves.append(sb)
            self.botmaster.maybeStartBuildsForBuilder(self.name)

    def attached(self, slave, remote, commands):
        """This is invoked by the BuildSlave when the self.slavename bot
        registers their builder.

        @type  slave: L{buildbot.buildslave.BuildSlave}
        @param slave: the BuildSlave that represents the buildslave as a whole
        @type  remote: L{twisted.spread.pb.RemoteReference}
        @param remote: a reference to the L{buildbot.slave.bot.SlaveBuilder}
        @type  commands: dict: string -> string, or None
        @param commands: provides the slave's version of each RemoteCommand

        @rtype:  L{twisted.internet.defer.Deferred}
        @return: a Deferred that fires (with 'self') when the slave-side
                 builder is fully attached and ready to accept commands.
        """
        for s in self.attaching_slaves + self.slaves:
            if s.slave == slave:
                # already attached to them. This is fairly common, since
                # attached() gets called each time we receive the builder
                # list from the slave, and we ask for it each time we add or
                # remove a builder. So if the slave is hosting builders
                # A,B,C, and the config file changes A, we'll remove A and
                # re-add it, triggering two builder-list requests, getting
                # two redundant calls to attached() for B, and another two
                # for C.
                #
                # Therefore, when we see that we're already attached, we can
                # just ignore it.
                return defer.succeed(self)

        sb = slavebuilder.SlaveBuilder()
        sb.setBuilder(self)
        self.attaching_slaves.append(sb)
        d = sb.attached(slave, remote, commands)
        d.addCallback(self._attached)
        d.addErrback(self._not_attached, slave)
        return d

    def _attached(self, sb):
        self.builder_status.addPointEvent(['connect', sb.slave.slavename])
        self.attaching_slaves.remove(sb)
        self.slaves.append(sb)

        self.updateBigStatus()

        return self

    def _not_attached(self, why, slave):
        # already log.err'ed by SlaveBuilder._attachFailure
        # TODO: remove from self.slaves (except that detached() should get
        #       run first, right?)
        log.err(why, 'slave failed to attach')
        self.builder_status.addPointEvent(['failed', 'connect',
                                           slave.slavename])
        # TODO: add an HTMLLogFile of the exception

    def detached(self, slave):
        """This is called when the connection to the bot is lost."""
        for sb in self.attaching_slaves + self.slaves:
            if sb.slave == slave:
                break
        else:
            log.msg("WEIRD: Builder.detached(%s) (%s)"
                    " not in attaching_slaves(%s)"
                    " or slaves(%s)" % (slave, slave.slavename,
                                        self.attaching_slaves,
                                        self.slaves))
            return
        if sb.state == BUILDING:
            # the Build's .lostRemote method (invoked by a notifyOnDisconnect
            # handler) will cause the Build to be stopped, probably right
            # after the notifyOnDisconnect that invoked us finishes running.
            pass

        if sb in self.attaching_slaves:
            self.attaching_slaves.remove(sb)
        if sb in self.slaves:
            self.slaves.remove(sb)

        self.builder_status.addPointEvent(['disconnect', slave.slavename])
        sb.detached() # inform the SlaveBuilder that their slave went away
        self.updateBigStatus()

    def updateBigStatus(self):
        if not self.builder_status:
            return
        if not self.slaves:
            self.builder_status.setBigState("offline")
        elif self.building or self.old_building:
            self.builder_status.setBigState("building")
        else:
            self.builder_status.setBigState("idle")

    @defer.inlineCallbacks
    def _startBuildFor(self, slavebuilder, buildrequests):
        """Start a build on the given slave.
        @param build: the L{base.Build} to start
        @param sb: the L{SlaveBuilder} which will host this build

        @return: (via Deferred) boolean indicating that the build was
        succesfully started.
        """

        # as of the Python versions supported now, try/finally can't be used
        # with a generator expression.  So instead, we push cleanup functions
        # into a list so that, at any point, we can abort this operation.
        cleanups = []
        def run_cleanups():
            try:
                while cleanups:
                    fn = cleanups.pop()
                    fn()
            except:
                log.err(failure.Failure(), "while running %r" % (run_cleanups,))

        # the last cleanup we want to perform is to update the big
        # status based on any other cleanup
        cleanups.append(lambda : self.updateBigStatus())

        build = self.config.factory.newBuild(buildrequests)
        build.setBuilder(self)
        log.msg("starting build %s using slave %s" % (build, slavebuilder))

        # set up locks
        build.setLocks(self.config.locks)
        cleanups.append(lambda : slavebuilder.slave.releaseLocks())

        if len(self.config.env) > 0:
            build.setSlaveEnvironment(self.config.env)

        # append the build to self.building
        self.building.append(build)
        cleanups.append(lambda : self.building.remove(build))

        # update the big status accordingly
        self.updateBigStatus()

        #check slave is still available
        ready = slavebuilder in self.getAvailableSlaveBuilders()
        if ready:
            try:
                ready = yield slavebuilder.prepare(self.builder_status, build)
            except:
                log.err(failure.Failure(), 'while preparing slavebuilder:')
                ready = False

        # If prepare returns True then it is ready and we start a build
        # If it returns false then we don't start a new build.
        if not ready:
            log.msg("slave %s can't build %s after all; re-queueing the "
                    "request" % (build, slavebuilder))
            run_cleanups()
            defer.returnValue(False)
            return

        # ping the slave to make sure they're still there. If they've
        # fallen off the map (due to a NAT timeout or something), this
        # will fail in a couple of minutes, depending upon the TCP
        # timeout.
        #
        # TODO: This can unnecessarily suspend the starting of a build, in
        # situations where the slave is live but is pushing lots of data to
        # us in a build.
        log.msg("starting build %s.. pinging the slave %s"
                % (build, slavebuilder))
        try:
            ping_success = yield slavebuilder.ping()
        except:
            log.err(failure.Failure(), 'while pinging slave before build:')
            ping_success = False

        if not ping_success:
            log.msg("slave ping failed; re-queueing the request")
            run_cleanups()
            defer.returnValue(False)
            return

        # The buildslave is ready to go. slavebuilder.buildStarted() sets its
        # state to BUILDING (so we won't try to use it for any other builds).
        # This gets set back to IDLE by the Build itself when it finishes.
        slavebuilder.buildStarted()
        cleanups.append(lambda : slavebuilder.buildFinished())

        # tell the remote that it's starting a build, too
        try:
            yield slavebuilder.remote.callRemote("startBuild")
        except:
            log.err(failure.Failure(), 'while calling remote startBuild:')
            run_cleanups()
            defer.returnValue(False)
            return

        # create the BuildStatus object that goes with the Build
        bs = self.builder_status.newBuild()

        # record the build in the db - one row per buildrequest
        try:
            bids = []
            for req in build.requests:
                bid = yield self.master.db.builds.addBuild(req.id, bs.number)
                bids.append(bid)
        except:
            log.err(failure.Failure(), 'while adding rows to build table:')
            run_cleanups()
            defer.returnValue(False)
            return

        # let status know
        self.master.status.build_started(req.id, self.name, bs)

        # start the build. This will first set up the steps, then tell the
        # BuildStatus that it has started, which will announce it to the world
        # (through our BuilderStatus object, which is its parent).  Finally it
        # will start the actual build process.  This is done with a fresh
        # Deferred since _startBuildFor should not wait until the build is
        # finished.
        d = build.startBuild(bs, self.expectations, slavebuilder)
        d.addCallback(self.buildFinished, slavebuilder, bids)
        # this shouldn't happen. if it does, the slave will be wedged
        d.addErrback(log.err)

        # make sure the builder's status is represented correctly
        self.updateBigStatus()

        defer.returnValue(True)

    def setupProperties(self, props):
        props.setProperty("buildername", self.name, "Builder")
        if len(self.config.properties) > 0:
            for propertyname in self.config.properties:
                props.setProperty(propertyname,
                        self.config.properties[propertyname],
                        "Builder")

    def buildFinished(self, build, sb, bids):
        """This is called when the Build has finished (either success or
        failure). Any exceptions during the build are reported with
        results=FAILURE, not with an errback."""

        # by the time we get here, the Build has already released the slave,
        # which will trigger a check for any now-possible build requests
        # (maybeStartBuilds)

        # mark the builds as finished, although since nothing ever reads this
        # table, it's not too important that it complete successfully
        brids = [br.id for br in build.requests]
        d = self.master.db.builds.finishBuilds(bids)
        # todo: get build number
        d.addCallback(lambda _ : self.master.db.builds.finishedMergedBuilds(brids, build.build_status.number))
        d.addErrback(log.err, 'while marking builds as finished (ignored)')

        results = build.build_status.getResults()
        self.building.remove(build)
        if results == RETRY:
            self._resubmit_buildreqs(build).addErrback(log.err)
        else:
            db = self.master.db
            d = db.buildrequests.completeBuildRequests(brids, results)
            d.addCallback(
                lambda _ : self._maybeBuildsetsComplete(build.requests))
            # nothing in particular to do with this deferred, so just log it if
            # it fails..
            d.addErrback(log.err, 'while marking build requests as completed')

        if sb.slave:
            sb.slave.releaseLocks()

        self.updateBigStatus()

    @defer.inlineCallbacks
    def _maybeBuildsetsComplete(self, requests, requestRemoved=False):
        # inform the master that we may have completed a number of buildsets
        for br in requests:
            yield self.master.maybeBuildsetComplete(br.bsid)
            # notify the master that the buildrequest was remove from queue
            if requestRemoved:
                self.master.buildRequestRemoved(br.bsid, br.id, self.name)

    def _resubmit_buildreqs(self, build):
        brids = [br.id for br in build.requests]
        return self.master.db.buildrequests.unclaimBuildRequests(brids)

    def setExpectations(self, progress):
        """Mark the build as successful and update expectations for the next
        build. Only call this when the build did not fail in any way that
        would invalidate the time expectations generated by it. (if the
        compile failed and thus terminated early, we can't use the last
        build to predict how long the next one will take).
        """
        if self.expectations:
            self.expectations.update(progress)
        else:
            # the first time we get a good build, create our Expectations
            # based upon its results
            self.expectations = Expectations(progress)
        log.msg("new expectations: %s seconds" % \
                self.expectations.expectedBuildTime())

    # notify the master that the buildrequests were removed from queue
    def notifyRequestsRemoved(self, buildrequests):
        for br in buildrequests:
            self.master.buildRequestRemoved(br.bsid, br.id, self.name)

    @defer.inlineCallbacks
    def mergeBuildingRequests(self, brdicts, brids, breqs):
        # check only the first br others will be compatible to merge
        brobj = yield self._brdictToBuildRequest(brdicts[0])
        for b in self.building:
            if self._defaultMergeRequestFn(b.requests[0], brobj):
                building = b.requests
                b.requests = b.requests + breqs
                try:
                    yield self.master.db.buildrequests.mergeBuildingRequest([b.requests[0]] + breqs, brids, b.build_status.number)
                except:
                    b.requests = building
                    raise

                log.msg("merge brids %s with building request %s " % (brids, b.requests[0].id))
                self.notifyRequestsRemoved(breqs)
                defer.returnValue(True)
                return
        defer.returnValue(False)


    def removeFromUnclaimRequestsList(self, brdicts, unclaimed_requests):
        brs = [ br for br in brdicts ]
        self._breakBrdictRefloops(brdicts)
        for br in brdicts:
            unclaimed_requests.remove(br)

    @defer.inlineCallbacks
    def updateUnclaimedRequest(self, unclaimed_requests):
        self._breakBrdictRefloops(unclaimed_requests)
        unclaimed_requests = \
            yield self.master.db.buildrequests.getBuildRequests(
                buildername=self.name, claimed=False)
        defer.returnValue(unclaimed_requests)
        return

    # Build Creation
    def getAvailableSlaveBuilders(self):
        return [sb for sb in self.slaves
                if sb.isAvailable()]

    def getSelectedSlaveFromBuildRequest(self, brdict):
        """
        Grab the selected slave and return the slave object
        if selected_slave property is not found then returns
        None
        """
        if self.buildRequestHasSelectedSlave(brdict):
            for sb in self.slaves:
                if sb.slave.slave_status.getName() == brdict['brobj'].properties.getProperty("selected_slave"):
                    return sb
        return None

    def buildRequestHasSelectedSlave(self, brdict):
        """
        Does the build request have a specified slave?
        """
        return brdict['brobj'].properties.hasProperty("selected_slave")

    @defer.inlineCallbacks
    def maybeStartBuild(self):
        # This method is called by the botmaster whenever this builder should
        # check for and potentially start new builds.  Do not call this method
        # directly - use master.botmaster.maybeStartBuildsForBuilder, or one
        # of the other similar methods if more appropriate

        # first, if we're not running, then don't start builds; stopService
        # uses this to ensure that any ongoing maybeStartBuild invocations
        # are complete before it stops.
        if not self.running:
            return

        # Check for available slaves.  If there are no available slaves, then
        # there is no sense continuing
        available_slavebuilders = self.getAvailableSlaveBuilders()

        # now, get the available build requests
        unclaimed_requests = \
            yield self.master.db.buildrequests.getBuildRequests(
                    buildername=self.name, claimed=False)

        if not unclaimed_requests:
            self.updateBigStatus()
            return

        # sort by submitted_at, so the first is the oldest
        unclaimed_requests.sort(key=lambda brd : brd['submitted_at'])

        # get the mergeRequests function for later
        mergeRequests_fn = self._getMergeRequestsFn()

        # match them up until we're out of options
        while (available_slavebuilders or self.building) and unclaimed_requests:
            # then choose a request (using nextBuild)
            if self.config.nextBuild:
                brdict =  yield self._chooseNextBuild(unclaimed_requests)
            else:
                brdict = yield self._chooseBuild(unclaimed_requests)

            if not brdict:
                break

            if brdict not in unclaimed_requests:
                log.msg(("nextBuild chose a nonexistent request for builder "
                         "'%s'; cannot start build") % self.name)
                break

            # merge the chosen request with any compatible requests in the
            # queue
            # todo: check it has compatible properties (force_build)
            brdicts = yield self._mergeRequests(brdict, unclaimed_requests,
                                                Builder._defaultMergeRequestFn)
            #mergeRequests_fn)

            # try to claim the build requests
            brids = [ brdict['brid'] for brdict in brdicts ]
            breqs = yield defer.gatherResults(
                [ self._brdictToBuildRequest(brdict)
                  for brdict in brdicts ])

            # merge current brdicts with currently running builds
            try:
                if (yield self.mergeBuildingRequests(brdicts, brids, breqs)):
                    self.removeFromUnclaimRequestsList(brdicts, unclaimed_requests)
                    continue
            except:
                unclaimed_requests = yield self.updateUnclaimedRequest(unclaimed_requests)
                continue

            # merge with compatible finished build in the same chain
            if 'startbrid' in brdict.keys() and brdict['startbrid'] is not None:
                # check if can be merged with finished build
                finished_br = yield self.master.db.buildrequests.findCompatibleFinishedBuildRequest(self.name, brdict['startbrid'])
                if finished_br:
                    merged_brids = yield self.master.db.buildrequests.getRequestsCompatibleToMerge(self.name, brdict['startbrid'], brids)
                    merged_brdicts = []
                    merged_breqs = []
                    for br in brdicts:
                        if br['brid'] in merged_brids:
                            merged_brdicts.append(br)

                    for brobj in breqs:
                        if brobj.id in merged_brids:
                            merged_breqs.append(brobj)

                    try:
                        log.msg("merge finished buildresquest %s with %s" % (finished_br, merged_brids))
                        yield self.master.db.buildrequests.mergeFinishedBuildRequest(finished_br, merged_brids)
                        yield self._maybeBuildsetsComplete(merged_breqs, requestRemoved=True)
                        self.removeFromUnclaimRequestsList(merged_brdicts, unclaimed_requests)
                    except:
                        unclaimed_requests = yield self.updateUnclaimedRequest(unclaimed_requests)
                    continue

            # if couldn't been merge try starting a new build, choose a slave (using nextSlave)
            if not available_slavebuilders:
                self.updateBigStatus()
                break

            #If we selected a specific slave check for availability
            if self.buildRequestHasSelectedSlave(brdict):
                slavebuilder = self.getSelectedSlaveFromBuildRequest(brdict)
                if slavebuilder.isAvailable() is False:
                    slavebuilder = None
            else:
                slavebuilder = yield self._chooseSlave(available_slavebuilders)

            if not slavebuilder:
                break

            if slavebuilder not in self.getAvailableSlaveBuilders():
                log.msg(("nextSlave chose a nonexistent or unavailable slave for builder "
                         "'%s'; cannot start build") % self.name)
                break

            try:
                yield self.master.db.buildrequests.mergePendingBuildRequests(brids)
                if len (brids) > 1:
                    log.msg("merge pending buildrequest %s with %s " % (brids[0], brids[1:]))

            except:
                # one or more of the build requests was already claimed;
                # re-fetch the now-partially-claimed build requests and keep
                # trying to match them

                if len (brids) > 1:
                    log.msg("build request already claimed, while merging pending buildrequest %s with %s "
                        % (brids[0], brids[1:]))
                unclaimed_requests = yield self.updateUnclaimedRequest(unclaimed_requests)
                # go around the loop again
                continue

            # claim was successful, so initiate a build for this set of
            # requests.  Note that if the build fails from here on out (e.g.,
            # because a slave has failed), it will be handled outside of this
            # loop. TODO: test that!

            # _startBuildFor expects BuildRequest objects, so cook some up
            build_started = yield self._startBuildFor(slavebuilder, breqs)

            if not build_started:
                # build was not started, so unclaim the build requests
                yield self.master.db.buildrequests.unclaimBuildRequests(brids)

                # and try starting builds again.  If we still have a working slave,
                # then this may re-claim the same buildrequests
                self.botmaster.maybeStartBuildsForBuilder(self.name)

            # finally, remove the buildrequests and slavebuilder from the
            # respective queues
            self.removeFromUnclaimRequestsList(brdicts, unclaimed_requests)
            available_slavebuilders.remove(slavebuilder)

        self._breakBrdictRefloops(unclaimed_requests)
        self.updateBigStatus()
        return

    # a few utility functions to make the maybeStartBuild a bit shorter and
    # easier to read

    def _chooseSlave(self, available_slavebuilders):
        """
        Choose the next slave, using the C{nextSlave} configuration if
        available, and falling back to C{random.choice} otherwise.

        @param available_slavebuilders: list of slavebuilders to choose from
        @returns: SlaveBuilder or None via Deferred
        """
        if self.config.nextSlave:
            return defer.maybeDeferred(lambda :
                    self.config.nextSlave(self, available_slavebuilders))
        else:
            return defer.succeed(random.choice(available_slavebuilders))

    @defer.inlineCallbacks
    def _chooseBuild(self, buildrequests):
        """
        Choose the next build from the given set of build requests (represented
        as dictionaries).  Defaults to returning the first request (earliest
        submitted).

        @param buildrequests: sorted list of build request dictionaries
        @returns: a build request dictionary or None via Deferred
        """
        sorted_requests = sorted(buildrequests, key=lambda br: (-br["priority"], br["submitted_at"]))
        for b in sorted_requests:
            d = yield defer.gatherResults([self._brdictToBuildRequest(b)])
            brdict = d[0].brdict
            if self.buildRequestHasSelectedSlave(brdict):
                selected_slave = self.getSelectedSlaveFromBuildRequest(brdict)
                if selected_slave is not None and selected_slave.isAvailable():
                    defer.returnValue(brdict)
            else:
                defer.returnValue(brdict)

        defer.returnValue(None)

    def _chooseNextBuild(self, buildrequests):
        # nextBuild expects BuildRequest objects, so instantiate them here
        # and cache them in the dictionaries
        d = defer.gatherResults([ self._brdictToBuildRequest(brdict)
                                  for brdict in buildrequests ],
                                consumeErrors=True)
        d.addCallback(lambda requestobjects :
        self.config.nextBuild(self, requestobjects))
        def to_brdict(brobj):
            # get the brdict for this object back
            return brobj.brdict
        d.addCallback(to_brdict)
        return d

    def _getMergeRequestsFn(self):
        """Helper function to determine which mergeRequests function to use
        from L{_mergeRequests}, or None for no merging"""
        # first, seek through builder, global, and the default
        mergeRequests_fn = self.config.mergeRequests
        if mergeRequests_fn is None:
            mergeRequests_fn = self.master.config.mergeRequests
        if mergeRequests_fn is None:
            mergeRequests_fn = True

        # then translate False and True properly
        if mergeRequests_fn is False:
            mergeRequests_fn = None
        elif mergeRequests_fn is True:
            mergeRequests_fn = Builder._defaultMergeRequestFn

        return mergeRequests_fn

    def getBoolProperty(self, req1, name):
        property = req1.properties.getProperty(name, False)
        if type(property) != bool:
            property = (property.lower() == "true")
        return property

    def propertiesMatch(self, req1, req2):
        #If the instances are the same then they match!
        if req1.bsid == req2.bsid:
            return True
        if req1.properties.has_key('selected_slave') or req2.properties.has_key('selected_slave'):
            return False
        if self.getBoolProperty(req1, "force_rebuild") != self.getBoolProperty(req2, "force_rebuild"):
            return False
        if self.getBoolProperty(req1, "force_chain_rebuild") != self.getBoolProperty(req2, "force_chain_rebuild"):
            return False
        return self.getBoolProperty(req1, "buildLatestRev") == self.getBoolProperty(req2, "buildLatestRev")

    def _defaultMergeRequestFn(self, req1, req2):
        if self.propertiesMatch(req1,req2):
            return req1.canBeMergedWith(req2)
        return False

    @defer.inlineCallbacks
    def _mergeRequests(self, breq, unclaimed_requests, mergeRequests_fn):
        """Use C{mergeRequests_fn} to merge C{breq} against
        C{unclaimed_requests}, where both are build request dictionaries"""
        # short circuit if there is no merging to do
        if not mergeRequests_fn or len(unclaimed_requests) == 1:
            defer.returnValue([ breq ])
            return

        # we'll need BuildRequest objects, so get those first
        unclaimed_request_objects = yield defer.gatherResults(
                [ self._brdictToBuildRequest(brdict)
                  for brdict in unclaimed_requests ])

        breq_object = unclaimed_request_objects[unclaimed_requests.index(breq)]

        # gather the mergeable requests
        # NOTE: This is assuming that it checks against itself
        # otherwise we get a return of an empty array
        merged_request_objects = []
        for other_breq_object in unclaimed_request_objects:
            if (yield defer.maybeDeferred(
                        lambda : mergeRequests_fn(self, breq_object,
                                                  other_breq_object))):
                merged_request_objects.append(other_breq_object)

        # convert them back to brdicts and return
        merged_requests = [ br.brdict for br in merged_request_objects ]
        defer.returnValue(merged_requests)

    def _brdictToBuildRequest(self, brdict):
        """
        Convert a build request dictionary to a L{buildrequest.BuildRequest}
        object, caching the result in the dictionary itself.  The resulting
        buildrequest will have a C{brdict} attribute pointing back to this
        dictionary.

        Note that this does not perform any locking - be careful that it is
        only called once at a time for each build request dictionary.

        @param brdict: dictionary to convert

        @returns: L{buildrequest.BuildRequest} via Deferred
        """
        if 'brobj' in brdict:
            return defer.succeed(brdict['brobj'])
        d = buildrequest.BuildRequest.fromBrdict(self.master, brdict)
        def keep(buildrequest):
            brdict['brobj'] = buildrequest
            buildrequest.brdict = brdict
            return buildrequest
        d.addCallback(keep)
        return d

    def _breakBrdictRefloops(self, requests):
        """Break the reference loops created by L{_brdictToBuildRequest}"""
        for brdict in requests:
            try:
                if hasattr(brdict['brobj'], 'brdict'):
                    del brdict['brobj'].brdict
            except KeyError:
                pass


class BuilderControl:
    implements(interfaces.IBuilderControl)

    def __init__(self, builder, control):
        self.original = builder
        self.control = control

    def submitBuildRequest(self, ss, reason, props=None):
        d = ss.getSourceStampSetId(self.control.master)
        def add_buildset(sourcestampsetid):
            return self.control.master.addBuildset(
                    builderNames=[self.original.name],
                    sourcestampsetid=sourcestampsetid, reason=reason, properties=props)
        d.addCallback(add_buildset)
        def get_brs((bsid,brids)):
            brs = BuildRequestStatus(self.original.name,
                                     brids[self.original.name],
                                     self.control.master.status)
            return brs
        d.addCallback(get_brs)
        return d

    @defer.inlineCallbacks
    def rebuildBuild(self, bs, reason="<rebuild, no reason given>", extraProperties=None):
        if not bs.isFinished():
            return

        # Make a copy of the properties so as not to modify the original build.
        properties = Properties()
        # Don't include runtime-set properties in a rebuild request
        properties.updateFromPropertiesNoRuntime(bs.getProperties())
        if extraProperties is None:
            properties.updateFromProperties(extraProperties)

        properties_dict = dict((k,(v,s)) for (k,v,s) in properties.asList())
        # set buildLatestRev to False when rebuilding
        if 'buildLatestRev' in properties_dict.keys():
            (v,s) = properties_dict['buildLatestRev']
            properties_dict['buildLatestRev'] = (False, s)

        ssList = bs.getSourceStamps(absolute=True)
        
        if ssList:
            sourcestampsetid = yield  ssList[0].getSourceStampSetId(self.control.master)
            dl = []
            for ss in ssList[1:]:
                # add defered to the list
                dl.append(ss.addSourceStampToDatabase(self.control.master, sourcestampsetid))
            yield defer.gatherResults(dl)

            bsid, brids = yield self.control.master.addBuildset(
                    builderNames=[self.original.name],
                    sourcestampsetid=sourcestampsetid, 
                    reason=reason, 
                    properties=properties_dict)
            defer.returnValue((bsid, brids))
        else:
            log.msg('Cannot start rebuild, rebuild has no sourcestamps for a new build')
            defer.returnValue(None)

    @defer.inlineCallbacks
    def getPendingBuildRequestControls(self, brids=None):
        master = self.original.master
        brdicts = yield master.db.buildrequests.getBuildRequests(
                buildername=self.original.name,
                claimed=False, brids=brids)

        # convert those into BuildRequest objects
        buildrequests = [ ]
        for brdict in brdicts:
            br = yield buildrequest.BuildRequest.fromBrdict(
                    self.control.master, brdict)
            buildrequests.append(br)

        # and return the corresponding control objects
        defer.returnValue([ buildrequest.BuildRequestControl(self.original, r)
                            for r in buildrequests ])

    def getBuild(self, number):
        return self.original.getBuild(number)

    def ping(self):
        if not self.original.slaves:
            self.original.builder_status.addPointEvent(["ping", "no slave"])
            return defer.succeed(False) # interfaces.NoSlaveError
        dl = []
        for s in self.original.slaves:
            dl.append(s.ping(self.original.builder_status))
        d = defer.DeferredList(dl)
        d.addCallback(self._gatherPingResults)
        return d

    def _gatherPingResults(self, res):
        for ignored,success in res:
            if not success:
                return False
        return True
