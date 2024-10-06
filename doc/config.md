# PLCT Server configuration

Most configuration options can be set either on the command line or in a configuration file, while some are configured using environment variables.

A command line option overrides the same option configured in a configuration file.

The configuration file is a JSON dictionary where each key represents an option.

## Configuration file name

There is no default configuration file, but you can set it either on command line or usingan environment variable.

### command line

Use `-c` or `--config` with a file name in the argument, like in the example: 
```
plct-serve -c dev-server.json
```

### environment variable

Use the `PLCT_SERVER_CONFIG_FILE` environment variable.

You don’t need to use the `plct-server` command line; instead, you can run the PLCT Server like any Python ASGI web application. For example, you can run the PLCT Server using the Uvicorn ASGI web server:

```
uvicorn plct_server.ui_main:app --host 127.0.0.1 --port 8000
```

In this case, you can use the `PLCT_SERVER_CONFIG_FILE` environment variable along with the appropriate configuration file to set the options.

## Verbose messages

You can configure verbose messages, which will effectively set the debug log level.

### cmmand line

Use `-v` or `--verbose`. Examle:
```
plct-serve -v
```

### configuration file

Use `verbose` key with `true` value. Example:

```json
{
  "verbose" : true
}
```

## Paths of PLCT projects to serve
### command line
Use positional command line arguments to specify the folder paths of PLCT projects. Example:

```
plct-serve ../courses/intro_to_prog ../courses/databases
```

Relative patsh are considered relative to the current folder.

### configuration file<a id='course_paths'></a>

Use the `course_paths` key. Example:
```json
{
  "course_paths": ["../courses/intro_to_prog", "../courses/databases"]
}
```
Relative paths are interpreted as follows:
- If [`content_url`](#content_url) is **not configured**, they are considered relative to the folder of the configuration file.
- If [`content_url`](#content_url) is **configured**, they are considered relative to the [`content_url`](#content_url). However, if [`content_url`](#content_url) is itself a relative path, it is considered relative to the folder of the configuration file.


## Base URL of of PLCT projects
### command line
The command line option is not implemented yet.
### configuration file<a id='content_url'></a>

Use the `content_url` key. It is intended for use in conjunction with [`course_paths`](#course_paths). Example:

```json
{
  "content_url" : "../courses",
  "course_paths": ["intro_to_prog", "databases"]
}
```
## Host and port

### command line

You may configure host and port the HTTP service should be bind to.

Use `-h` or `--host` option to set the host and `-p` or `--port` option to set the port. For instance:
```
plct-serve -h 127.0.0.1 -p 8000
```

### config file

Host and port options cannot be configured in a configuration file. These options are specific to the `plct-serve` command that embeds an HTTP server.











