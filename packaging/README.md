# Packaging

Distribution metadata for redx. Each target file pulls from the same source tree
in the parent directory.

| File                    | Used by                                          |
|-------------------------|--------------------------------------------------|
| `redx.svg`              | All: scalable icon installed under hicolor      |
| `redx.desktop`          | All Linux desktops: XDG application launcher    |
| `PKGBUILD`              | Arch / CachyOS: `makepkg -si` from this dir     |
| `build_appimage.sh`     | Single-file portable binary: `bash build_appimage.sh` |
| `io.github.mescon.redx.yml`        | Flatpak manifest: submit to Flathub             |

## Quick reference

### PyPI (any Python-savvy user)

```sh
pip install redx       # once published
redx                   # launches the GUI
```

### AUR (Arch / CachyOS / EndeavourOS / Manjaro)

```sh
cd packaging
makepkg -si
```

### AppImage (any Linux, no install)

```sh
# One-time setup:
curl -L -o /tmp/appimagetool.AppImage \
  https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x /tmp/appimagetool.AppImage

# Build:
bash packaging/build_appimage.sh
./build/redx-x86_64.AppImage
```

### Flatpak (cross-distro, sandboxed)

```sh
flatpak-builder --user --install --force-clean build-flatpak packaging/io.github.mescon.redx.yml
flatpak run io.github.mescon.redx
```

The Flatpak manifest is currently a skeleton. Before submitting to Flathub:
1. Run `flatpak-pip-generator send2trash` to produce a hash-pinned dependencies file
2. Reference that file as a module before redx
3. Validate with `flatpak-builder-lint --user manifest packaging/io.github.mescon.redx.yml`
