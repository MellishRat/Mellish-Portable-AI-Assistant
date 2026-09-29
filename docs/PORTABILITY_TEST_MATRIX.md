# Portability validation matrix

The automated test is `tests\Validate-Bootstrap.ps1`. Run it with
`-IncludeRuntime` to extract and verify the pinned standalone Python twice in a
path containing spaces. Add `-IncludeDependencies` to install the core and voice
requirements and assert their imports resolve inside the standalone runtime.

Before a public release, also exercise these cases on disposable Windows 10/11
machines or snapshots:

- No Python installed: install, then verify the selected folder's `python.exe`,
  `pip`, and `tkinter`.
- An unrelated Python 3.11 installed: confirm it is unchanged and Mellish uses
  only `runtime\python\python.exe`.
- Deleted previous Mellish folder: reinstall to a different destination.
- Interrupted download/extraction: retry and confirm the bad archive or staging
  tree is discarded safely.
- Partial first destination followed by a different destination, including one
  with spaces.
- Repeated `Repair or Add Models.bat` runs from the installed folder.
- Compare PATH, Python launcher registrations, Python uninstall entries and
  `.py` file associations before and after installation. Mellish must add none.
- Install both core and optional voice requirements with the selected runtime,
  using only `python.exe -m pip`.
- Run the application, microphone transcription and TTS after moving the whole
  installation folder to another location on the same compatible PC.

Hardware drivers, microphone permissions, audio devices and Windows shortcuts
remain machine-specific and should be redetected or recreated after a move.
