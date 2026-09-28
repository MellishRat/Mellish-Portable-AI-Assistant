# Release checklist

- [ ] Decide whether the repository will be public or private.
- [ ] Choose and add a source-code licence. Until then, copyright is retained.
- [ ] Review every model URL, model card and licence.
- [ ] Update pinned Python/Ollama versions and verification metadata deliberately.
- [ ] Run the PowerShell parser test and bootstrap dry run.
- [ ] Test a real clean Windows 10 or 11 x64 virtual machine.
- [ ] Test NVIDIA, CPU-only and low-disk-space paths.
- [ ] Verify minimal and full installation recommendations.
- [ ] Confirm repair/add-model mode preserves chats and settings.
- [ ] Confirm no `config`, `chats`, `cache`, `voice`, `models` or credentials are staged.
- [ ] Build the ZIP with `build_release.ps1` and publish its SHA-256 value.
- [ ] Explain that an unsigned ZIP may trigger a Windows SmartScreen warning.
