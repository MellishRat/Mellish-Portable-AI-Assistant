# Release checklist

- [ ] Decide whether the repository will be public or private.
- [ ] Choose and add a source-code licence. Until then, copyright is retained.
- [ ] Review every model URL, model card and licence.
- [ ] Review the pinned python-build-standalone release, archive SHA-256 and bundled licence notices.
- [ ] Update pinned Python/Ollama versions and verification metadata deliberately.
- [ ] Run `tests\Validate-Bootstrap.ps1 -IncludeRuntime` and the bootstrap dry runs.
- [ ] Test a real clean Windows 10 or 11 x64 virtual machine.
- [ ] Test with another Python 3.11 installed and after manually deleting an old Mellish folder.
- [ ] Test interruption, destination changes, spaces in paths and repeated repair runs.
- [ ] Confirm no Python PATH, launcher, uninstall entry or file association is added.
- [ ] Confirm the selected folder's Python can import pip and tkinter.
- [ ] Confirm core and optional voice requirements install with `python.exe -m pip`.
- [ ] Test NVIDIA, CPU-only and low-disk-space paths.
- [ ] Verify minimal and full installation recommendations.
- [ ] Confirm repair/add-model mode preserves chats and settings.
- [ ] Confirm no `config`, `chats`, `cache`, `voice`, `models` or credentials are staged.
- [ ] Build the ZIP with `build_release.ps1` and publish its SHA-256 value.
- [ ] Explain that an unsigned ZIP may trigger a Windows SmartScreen warning.
