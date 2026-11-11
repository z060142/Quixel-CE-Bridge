# QuixelCEBridge (plugin folder)

This plugin runs on **CrythonNative** (the `CrythonNative` Sandbox plugin must be built and loaded).
Drop this whole folder into a CrythonNative plugin directory:

```
<engine root>\Editor\Python\crython_plugins\QuixelCEBridge\
<project root>\Editor\Python\crython_plugins\QuixelCEBridge\
```

or add the folder that *contains* `QuixelCEBridge` to the `CRYTHON_PLUGIN_PATH` environment variable
(`;` separated). The old `Editor\Python\plugins\` location (stock `sandbox.*` API) is no longer supported.

Full documentation (Bridge-side setup, config reference, troubleshooting):

<https://github.com/z060142/Quixel-CE-Bridge#readme>
