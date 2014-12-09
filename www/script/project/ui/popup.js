/*global define, requirejs, jQuery, confirm*/
define(function (require) {

    "use strict";

    var $ = require('jquery'),
        helpers = require('helpers'),
        hb = require('project/handlebars-extend'),
        timeElements = require('timeElements'),
        toastr = require('toastr'),
        popups = hb.popups;

    require('libs/jquery.form');

    var $body = $("body");

    // Extend our jquery object with popup widget
    (function ($) {

        $.fn.popup = function (options) {
            var $elem = $(this);
            var opts = $.extend({}, $.fn.popup.defaults, options);
            $elem.settings = opts;

            var privateFunc = {
                init: function () {
                    privateFunc.clear();
                    privateFunc.createID();
                    if (privateFunc.createHTML()) {
                        opts.onCreate($elem);

                        if (opts.autoShow) {
                            $elem.ready(function () {
                                privateFunc.showPopup();
                            });
                        }
                    }
                },
                createID: function createID() {
                    if ($elem.popupID === undefined) {
                        var id = "",
                            possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
                            i;

                        for (i = 0; i < 5; i += 1) {
                            id += possible.charAt(Math.floor(Math.random() * possible.length));
                        }

                        $elem.popupID = id;
                    }
                },
                getID: function getID() {
                    return $elem.popupID;
                },
                getCloseClickEvent: function getCloseClickEvent() {
                    var id = privateFunc.getID();
                    return "click.katana.popup" + id + " touchstart.katana.popup" + id;
                },
                createHTML: function () {
                    $elem.addClass("more-info-box more-info-box-js").
                        append("<span class='close-btn'></span>").
                        append(opts.title).
                        attr("data-ui-popup", true).hide();

                    if (opts.url) {
                        $.ajax(opts.url).
                            done(function (data) {
                                $elem.append(data);
                                opts.onCreate($elem);
                                privateFunc.showPopup();

                                return true;
                            });

                        return false;
                    }

                    $elem.append($("<div/>").html(opts.html));
                    return true;
                },
                clear: function () {
                    if ($elem.attr("data-ui-popup") === "true") {
                        if (opts.destroyAfter) {
                            helpers.clearChildEvents($elem);
                            $elem.off();
                            $elem.remove();
                            delete opts.title;
                            delete opts.html;

                            $(document).off(privateFunc.getCloseClickEvent());
                            $(window).off("resize.katana.popup");

                            $elem = null;
                        } else {
                            $elem.empty();
                        }
                    }
                },
                showPopup: function () {

                    //Delay these things slightly so the DOM has time to update
                    setTimeout(function () {
                        if ($elem !== null) {
                            privateFunc.initCloseButton();
                            helpers.jCenter($elem);
                            if (opts.center) {
                                $(window).on("resize.katana.popup", function () {
                                    helpers.jCenter($elem);
                                });
                            }
                        }
                    }, 1);

                    if (opts.animate) {
                        $elem.fadeIn(opts.showAnimation, function () {
                            opts.onShow($elem);
                        });
                    } else {
                        $elem.show();
                        opts.onShow($elem);
                    }
                },
                hidePopup: function () {
                    //Remove event handlers
                    $(document).off(privateFunc.getCloseClickEvent());
                    $(window).off("resize.katana.popup");

                    if (opts.animate) {
                        $elem.fadeOut(opts.hideAnimation, function () {
                            $elem.hide();
                            privateFunc.clear();
                            opts.onHide($elem);
                        });
                    } else {
                        $elem.hide();
                        privateFunc.clear();
                        opts.onHide($elem);
                    }
                },
                initCloseButton: function () {
                    $(document).on(privateFunc.getCloseClickEvent(), function (e) {
                        if ((!$elem.is(e.target) && $elem.has(e.target).length === 0) || $elem.find(".close-btn").is(e.target)) {
                            if ($elem.is(":visible")) {
                                privateFunc.hidePopup();
                                $(this).off("click.katana.popup touchstart.katana.popup", e.callee);
                            }
                        }
                    });
                }
            };

            $elem.showPopup = function () {
                privateFunc.showPopup();
            };

            $elem.hidePopup = function () {
                privateFunc.hidePopup();
            };

            $elem.options = function (options) {
                opts = $.extend({}, $.fn.popup.defaults, opts, options);
            };

            //Initialise the popup on this element
            return $elem.each(function () {
                privateFunc.init();
                opts.initalized = true;
            });
        };

        $.fn.popup.defaults = {
            title: "",
            html: undefined,
            url: undefined,
            destroyAfter: false,
            autoShow: true,
            center: true,
            animate: true,
            showAnimation: "fast",
            hideAnimation: "fast",
            onCreate: function ($elem) {
                return undefined;
            },
            onShow: function ($elem) {
                return undefined;
            },
            onHide: function ($elem) {
                return undefined;
            }
        };
    }(jQuery));


    var popup;

    popup = {
        init: function () {
            // Display the codebases form in a popup
            popup.initCodebaseBranchesPopup($("#codebasesBtn"));
        },
        validateForm: function (formContainer) { // validate the forcebuildform
            var formEl = $('.command_forcebuild', formContainer);
            var excludeFields = ':button, :hidden, :checkbox, :submit';
            $('.grey-btn', formEl).bind("click.katana", function (e) {

                var allInputs = $('input', formEl).not(excludeFields);

                var rev = allInputs.filter(function () {
                    return this.name.indexOf("revision") >= 0;
                });

                var emptyRev = rev.filter(function () {
                    return this.value === "";
                });

                if (emptyRev.length > 0 && emptyRev.length < rev.length) {

                    rev.each(function () {
                        if ($(this).val() === "") {
                            $(this).addClass('not-valid');
                        } else {
                            $(this).removeClass('not-valid');
                        }
                    });

                    $('.form-message', formEl).hide();

                    if (!$('.error-input', formEl).length) {
                        var template = popups({'errorinput': 'true', 'text': 'Fill out the empty revision fields or clear all before submitting'});
                        var errorinput = $(template);
                        $(formEl).prepend(errorinput);
                    }
                    e.preventDefault();
                }
            });
        },
        initJSONPopup: function (jsonPopupElem, data) {
            var $jsonPopupElem = $(jsonPopupElem);

            $jsonPopupElem.bind("click.katana", function (e) {
                e.preventDefault();
                var html = popups(data);
                $body.append($("<div/>").popup({
                    title: "",
                    html: html,
                    onShow: function () {
                        if (data.showRunningBuilds !== undefined) {
                            helpers.delegateToProgressBar($('div.more-info-box-js div.percent-outer-js'));
                        }
                        timeElements.updateTimeObjects();
                    }
                }));
            });
        },
        initCodebaseBranchesPopup: function (codebaseElem) {
            var $codebaseElem = $(codebaseElem),
                codebasesURL = $codebaseElem.attr("data-codebases-url");

            $codebaseElem.bind("click.katana", function (event) {
                event.preventDefault();

                $("#preloader").preloader("showPreloader");

                $.get(codebasesURL).
                    done(function (html) {
                        $("#preloader").preloader("hidePreloader");
                        requirejs(['selectors'], function (selectors) {
                            var fw = $(html).find('#formWrapper');
                            fw.children('#getForm').attr('action', window.location.href);
                            fw.find('.blue-btn[type="submit"]').val('Update');


                            $body.append($("<div/>").popup({
                                title: $('<h3 class="codebases-head" />').html("Select Branches"),
                                html: fw,
                                destroyAfter: true,
                                onCreate: function ($elem) {
                                    $elem.css("max-width", "80%");
                                },
                                onShow: function ($elem) {
                                    selectors.init();
                                    helpers.jCenter($elem);
                                    $(window).on("resize.popup", function () {
                                        helpers.jCenter($elem);
                                    });
                                }
                            }));
                        });
                    });
            });
        },
        initPendingPopup: function (pendingElem) {
            var $pendingElem = $(pendingElem),
                builder_name = encodeURIComponent($pendingElem.attr('data-builderName')),
                urlParams = helpers.codebasesFromURL({}),
                paramsString = helpers.urlParamsToString(urlParams),
                url = "/json/pending/{0}/?{1}".format(builder_name, paramsString);

            function openPopup() {
                $("#preloader").preloader("showPreloader");

                $.ajax({
                    url: url,
                    cache: false,
                    dataType: "json",
                    success: function (data) {
                        $("#preloader").preloader("hidePreloader");

                        var cancelURL = data[0].builderURL;
                        var properties = "";
                        if (cancelURL.indexOf("?") > -1) {
                            var split = cancelURL.split("?");
                            properties += split[1] + "&";
                            cancelURL = split[0];
                        }

                        properties += "returnpage=builders_json";
                        cancelURL = "{0}/cancelbuild?{1}".format(cancelURL, properties);

                        var html = popups({pendingJobs: data, showPendingJobs: true, cancelURL: cancelURL});

                        $body.append($("<div/>").popup({
                            html: html,
                            destroyAfter: true,
                            onCreate: function ($elem) {
                                var waitingtime = $elem.find('.waiting-time-js');
                                waitingtime.each(function (i) {
                                    timeElements.addElapsedElem($(this), data[i].submittedAt);
                                    timeElements.updateTimeObjects();
                                });

                                $elem.find('form').ajaxForm({
                                    success: function (data, text, xhr, $form) {
                                        requirejs(['realtimePages'], function (realtimePages) {
                                            setTimeout(function () {
                                                var name = "builders";
                                                realtimePages.updateSingleRealTimeData(name, data);
                                            }, 300);
                                        });

                                        var cancelAll = $form.attr("id") === "cancelall";
                                        if (!cancelAll) {
                                            $form.parent().remove();
                                        }

                                        if (cancelAll || $elem.find('li').length === 1) {
                                            $elem.hidePopup();
                                        }
                                    }
                                });
                            },
                            onHide: function ($elem) {
                                timeElements.clearTimeObjects($elem);
                            }
                        }));
                    }
                });
            }

            $pendingElem.bind("click.katana", function (event) {
                event.preventDefault();
                openPopup();
            });
        },
        initRunBuild: function (customBuildElem, instantBuildElem, redirectToBuilder) {
            var $customBuild = $(customBuildElem),
                $instantBuild = $(instantBuildElem);

            if ($customBuild.length === 0) {
                //Bailing early as we didn't find our elements
                return;
            }

            function openPopup(instantBuild) {
                var builderURL = $customBuild.attr('data-builder-url'),
                    dataReturnPage = $customBuild.attr('data-return-page'),
                    builderName = $customBuild.attr('data-builder-name'),
                    title = $customBuild.attr('data-popup-title'),
                    url = location.protocol + "//" + location.host + "/forms/forceBuild",
                    urlParams = helpers.codebasesFromURL({builder_url: builderURL, builder_name: builderName, return_page: dataReturnPage});


                $("#preloader").preloader("showPreloader");

                function errorCreatingBuild() {
                    toastr.error('There was an error when creating your build please try again later', 'Error', {
                        iconClass: 'failure'
                    });
                }

                $.get(url, urlParams)
                    .done(function (html) {
                        // Create popup
                        var $popup = $("<div/>").popup({
                            title: $('<h2 class="small-head" />').text(title),
                            html: html,
                            destroyAfter: true,
                            autoShow: false,
                            onCreate: function ($elem) {
                                popup.validateForm($elem);

                                //Setup AJAX form and instant builds
                                var $form = $elem.find('form'),
                                    formOptions = {
                                        beforeSerialize: function () {
                                            // Trim revision fields
                                            $.each($form.find("[name*=_revision]"), function (i, el) {
                                                var $el = $(el);
                                                $el.val($.trim($el.val()));
                                            });
                                        },
                                        beforeSubmit: function () {
                                            $elem.hidePopup();
                                            $("#preloader").preloader("hidePreloader");

                                            require(["rtGlobal"], function (rtGlobal) {
                                                if (rtGlobal.isKatanaLoaded()) {
                                                    return confirm('The build load is currently very high, if possible ' +
                                                    'please wait until the build load goes down. \n\nAre you sure ' +
                                                    'you want to request this build?');
                                                }
                                            });
                                        },
                                        success: function (data) {
                                            if (redirectToBuilder) {
                                                window.location.href = builderURL;
                                            }
                                            requirejs(['realtimePages'], function (realtimePages) {
                                                var name = dataReturnPage.replace("_json", "");
                                                realtimePages.updateSingleRealTimeData(name, data);
                                            });
                                            $("#preloader").preloader("hidePreloader");

                                            toastr.info('Your build will start shortly', 'Info', {
                                                iconClass: 'info'
                                            });
                                        },
                                        error: function () {
                                            $("#preloader").preloader("hidePreloader");
                                            errorCreatingBuild();
                                        }
                                    };

                                $form.ajaxForm(formOptions);

                                if (instantBuild) {
                                    $form.ajaxSubmit(formOptions);
                                }
                            }
                        });

                        $body.append($popup);
                        if (!instantBuild) {
                            $popup.showPopup();
                        }
                    })
                    .fail(function () {
                        errorCreatingBuild();
                    })
                    .always(function () {
                        $("#preloader").preloader("hidePreloader");
                    });
            }

            $customBuild.bind("click.katana", function (event) {
                event.preventDefault();
                openPopup(false);
            });

            $instantBuild.bind("click.katana", function (event) {
                event.preventDefault();
                openPopup(true);
            });
        },
        initArtifacts: function (artifactList, artifactElem) {
            var $artifactElem = $(artifactElem);

            $artifactElem.bind("click.katana", function (event) {
                event.preventDefault();

                var html = "";
                if (artifactList !== undefined) {
                    $.each(artifactList, function (name, url) {
                        html += '<li class="artifact-js"><a target="_blank" href="{1}">{0}</a></li>'.format(name, url);
                    });
                    html = $('<ul/>').addClass("builders-list").html(html);
                    var $popup = $("<div/>").popup({
                        title: "<h3>Artifacts</h3>",
                        html: html,
                        destroyAfter: true
                    });

                    $body.append($popup);
                }
            });
        }
    };
    return popup;
});
