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

import mock
from twisted.trial import unittest
from twisted.internet import defer
from buildbot.data import builders
from buildbot.test.util import validation, endpoint, interfaces
from buildbot.test.fake import fakemaster, fakedb

class Builder(endpoint.EndpointMixin, unittest.TestCase):

    endpointClass = builders.BuilderEndpoint

    def setUp(self):
        self.setUpEndpoint()
        return self.db.insertTestData([
            fakedb.Builder(id=1, name=u'buildera'),
            fakedb.Builder(id=2, name=u'builderb'),
            fakedb.Master(id=13),
            fakedb.BuilderMaster(id=1, builderid=2, masterid=13),
        ])

    def tearDown(self):
        self.tearDownEndpoint()

    def test_get_existing(self):
        d = self.callGet(dict(), dict(builderid=2))
        @d.addCallback
        def check(builder):
            validation.verifyData(self, 'builder', {}, builder)
            self.assertEqual(builder['name'], u'builderb')
        return d

    def test_get_missing(self):
        d = self.callGet(dict(), dict(builderid=99))
        @d.addCallback
        def check(builder):
            self.assertEqual(builder, None)
        return d

    def test_get_existing_with_master(self):
        d = self.callGet(dict(), dict(masterid=13, builderid=2))
        @d.addCallback
        def check(builder):
            validation.verifyData(self, 'builder', {}, builder)
            self.assertEqual(builder['name'], u'builderb')
        return d

    def test_get_existing_with_different_master(self):
        d = self.callGet(dict(), dict(masterid=14, builderid=2))
        @d.addCallback
        def check(builder):
            self.assertEqual(builder, None)
        return d

    def test_get_missing_with_master(self):
        d = self.callGet(dict(), dict(masterid=13, builderid=99))
        @d.addCallback
        def check(builder):
            self.assertEqual(builder, None)
        return d


class Builders(endpoint.EndpointMixin, unittest.TestCase):

    endpointClass = builders.BuildersEndpoint

    def setUp(self):
        self.setUpEndpoint()
        return self.db.insertTestData([
            fakedb.Builder(id=1, name=u'buildera'),
            fakedb.Builder(id=2, name=u'builderb'),
            fakedb.Master(id=13),
            fakedb.BuilderMaster(id=1, builderid=2, masterid=13),
        ])


    def tearDown(self):
        self.tearDownEndpoint()


    def test_get(self):
        d = self.callGet(dict(), dict())
        @d.addCallback
        def check(builders):
            [ validation.verifyData(self, 'builder', {}, b) for b in builders ]
            self.assertEqual(sorted([b['builderid'] for b in builders]),
                             [1, 2])
        return d

    def test_get_masterid(self):
        d = self.callGet(dict(), dict(masterid=13))
        @d.addCallback
        def check(builders):
            [ validation.verifyData(self, 'builder', {}, b) for b in builders ]
            self.assertEqual(sorted([b['builderid'] for b in builders]),
                             [2])
        return d

    def test_get_masterid_missing(self):
        d = self.callGet(dict(), dict(masterid=14))
        @d.addCallback
        def check(builders):
            self.assertEqual(sorted([b['builderid'] for b in builders]),
                             [])
        return d

    def test_startConsuming(self):
        self.callStartConsuming({}, {},
                expected_filter=('builder', None, None))


class BuilderResourceType(interfaces.InterfaceTests, unittest.TestCase):

    def setUp(self):
        self.master = fakemaster.make_master(testcase=self,
                wantMq=True, wantDb=True, wantData=True)
        self.rtype = builders.BuildersResourceType(self.master)
        return self.master.db.insertTestData([
            fakedb.Master(id=13),
            fakedb.Master(id=14),
        ])

    def test_signature_updateBuilderList(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.updateBuilderList, # fake
            self.rtype.updateBuilderList) # real
        def updateBuilderList(self, masterid, builderNames):
            pass

    @defer.inlineCallbacks
    def test_updateBuilderList(self):
        # add one builder master
        yield self.rtype.updateBuilderList(13, [ u'somebuilder' ])
        self.assertEqual(sorted((yield self.master.db.builders.getBuilders())),
            sorted([
                dict(id=1, masterids=[13], name='somebuilder'),
        ]))
        self.master.mq.assertProductions([(('builder', '1', 'started'),
              {'builderid': 1, 'masterid': 13, 'name': u'somebuilder'})])

        # add another
        yield self.rtype.updateBuilderList(13, [ u'somebuilder', u'another' ])
        self.assertEqual(sorted((yield self.master.db.builders.getBuilders())),
            sorted([
                dict(id=1, masterids=[13], name='somebuilder'),
                dict(id=2, masterids=[13], name='another'),
        ]))
        self.master.mq.assertProductions([(('builder', '2', 'started'),
              {'builderid': 2, 'masterid': 13, 'name': u'another'})])

        # add one for another master
        yield self.rtype.updateBuilderList(14, [ u'another' ])
        self.assertEqual(sorted((yield self.master.db.builders.getBuilders())),
            sorted([
                dict(id=1, masterids=[13], name='somebuilder'),
                dict(id=2, masterids=[13, 14], name='another'),
        ]))
        self.master.mq.assertProductions([(('builder', '2', 'started'),
              {'builderid': 2, 'masterid': 14, 'name': u'another'})])

        # remove both for the first master
        yield self.rtype.updateBuilderList(13, [ ])
        self.assertEqual(sorted((yield self.master.db.builders.getBuilders())),
            sorted([
                dict(id=1, masterids=[], name='somebuilder'),
                dict(id=2, masterids=[14], name='another'),
        ]))
        self.master.mq.assertProductions([
            (('builder', '1', 'stopped'),
              {'builderid': 1, 'masterid': 13, 'name': u'somebuilder'}),
            (('builder', '2', 'stopped'),
              {'builderid': 2, 'masterid': 13, 'name': u'another'}),
        ])

    @defer.inlineCallbacks
    def test__masterDeactivated(self):
        # this method just calls updateBuilderList, so test that.
        self.rtype.updateBuilderList = mock.Mock(
                spec=self.rtype.updateBuilderList)
        yield self.rtype._masterDeactivated(10)
        self.rtype.updateBuilderList.assert_called_with(10, [])