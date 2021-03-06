/*global module*/
module.exports = function (grunt) {
    "use strict";

    var target = "dev";
    if (grunt.option("prod")) {
        target = "prod";
    }

    // Configuration goes here
    grunt.initConfig({
        files: {
            css: {
                src: ["sass"],
                src_watch: ["sass/**/*.scss"],
                dest: "prod/css",
                src_css: ['*.css', '!*.min.css'],
                ext: '.css'
            },
            js: {
                src: [
                    "script/libs/**/*.js",
                    "script/plugins/**/*.js",
                    "script/project/**/*.js",
                    "script/templates/*.handlebars",
                    "script/main.js"
                ],
                dest: "prod/",
                requirejs: {
                    dest: "prod/script/main.js",
                    include: [
                        "require.js",
                        "testResults",
                        "buildLog",
                        "buildLogiFrame",
                        "login"
                    ]
                }
            },
            html: {
                src: [
                    "templates/**/*.html"
                ]
            },
            handlebars: {
                src: [
                    "script/templates/**/*.hbs"
                ],
                dest: "generated/precompiled.handlebars.js"
            }
        },
        compass: {
            options: {
                sassDir: "<%= files.css.src %>",
                cssDir: "<%= files.css.dest %>"
            },
            prod: {
                options: {
                    force: true,
                    environment: "production",
                    outputStyle: "nested"
                }
            },
            dev: {
                options: {
                    debugInfo: true,
                    environment: "development",
                    outputStyle: "nested"
                }
            }
        },
        cssmin: {
            options: {
                keepBreaks: true
            },
            minify: {
                files: [
                    {
                        expand: true,
                        cwd: '<%= files.css.dest %>',
                        src: '<%= files.css.src_css %>',
                        dest: '<%= files.css.dest %>',
                        ext: '<%= files.css.ext %>'
                    }
                ]
            }
        },
        requirejs: {
            options: {
                baseUrl: "script/",
                mainConfigFile: "script/main.js",
                name: "main",
                out: "<%= files.js.requirejs.dest %>",
                include: "<%= files.js.requirejs.include %>",
                preserveLicenseComments: false,
                generateSourceMaps: true,
                fileExclusionRegExp: /^test$|^karma\.config\.js|^coverage$/,
                findNestedDependencies: true
            },
            dev: {
                options: {
                    optimize: "none"
                }
            },
            prod: {
                options: {
                    optimize: "uglify2"
                }
            }
        },
        watch: {
            options: {
                livereload: true
            },
            css: {
                files: ["<%= files.css.src_watch %>"],
                tasks: ["compass:" + target, "cssmin"]
            },
            js: {
                files: ["<%= files.js.src %>"],
                tasks: ["requirejs:" + target]
            },
            html: {
                files: ["<%= files.html.src %>"]
            },
            handlebars: {
                files: ["<%= files.handlebars.src %>"],
                tasks: ["handlebars:compile", "requirejs:" + target]
            }
        },
        karma: {
            options: {
                configFile: "script/karma.config.js",
                browsers: ["Chrome"],
                singleRun: true,
                runnerPort: 9876
            },
            unit: {},
            coverage: {
                reporters: "coverage"
            }
        },
        open: {
            coverage: {
                path: function () {
                    var reports = grunt.file.expand('coverage/Chrome*/index.html');
                    return reports[reports.length - 1].toString();
                }
            }
        },
        handlebars: {
            compile: {
                options: {
                    amd: true,
                    partialRegex: /[\w\W]*/,
                    partialsPathRegex: /\/partials\//,
                    partialsUseNamespace: true,
                    namespace: function (filename) {
                        var names = filename.replace(/^script\/templates([\w\W\/]*)(\/[\w\-\/]+)(\.hbs)$/, 'KT$1');
                        names = names.split('/').join('.').replace(".hbs", "");
                        return names;
                    },
                    processPartialName: function (filePath) {
                        //Get the namespace for the partial
                        var ns = filePath.replace(/^script\/templates\/partials([\w\W\/]*)(\/[\w\-\/]+)(\.hbs)$/, '$1:');
                        ns = ns.replace("/", "");

                        //Grab the partial name and camelCase it
                        var pieces = filePath.split("/");
                        var partialName = pieces[pieces.length - 1].replace(".hbs", "");
                        partialName = partialName.replace(/-([a-z])/g, function (g) {
                            return g[1].toUpperCase();
                        });
                        partialName = ns.replace(/\//g, ":") + partialName;

                        return partialName;
                    },
                    processName: function (filePath) {
                        var pieces = filePath.split("/");
                        var partialName = pieces[pieces.length - 1];
                        partialName = partialName.replace(/-([a-z])/g, function (g) {
                            return g[1].toUpperCase();
                        });

                        return partialName.replace(".hbs", "");
                    }
                },
                src: ["<%= files.handlebars.src %>"],
                dest: "<%= files.handlebars.dest %>"
            }
        }
    });

    // Load plugins here
    grunt.loadNpmTasks("grunt-contrib-compass");
    grunt.loadNpmTasks("grunt-contrib-watch"); // run grunt watch for converting sass files to css in realtime
    grunt.loadNpmTasks("grunt-contrib-requirejs");
    grunt.loadNpmTasks("grunt-contrib-handlebars");
    grunt.loadNpmTasks("grunt-karma");
    grunt.loadNpmTasks('grunt-contrib-cssmin');
    grunt.loadNpmTasks('grunt-open');

    // Define your tasks here
    grunt.registerTask("prod", ["test", "build:prod"]);
    grunt.registerTask("build", "Builds all of our resources", function (overrideTarget) {
        if (overrideTarget !== undefined) {
            target = overrideTarget;
        }
        grunt.task.run(["compass:" + target, "cssmin", "handlebars:compile", "requirejs:" + target]);
    });
    grunt.registerTask("test", ["karma:unit"]);
    grunt.registerTask("coverage", ["karma:coverage", "open:coverage"]);
    grunt.registerTask("default", ["build", "watch"]);

};
