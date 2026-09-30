# touchHLE Zombie Farm

English | [中文](README.md)

This branch is intended for running Playforge's Zombie Farm / ZFR. It includes compatibility fixes and debugging helpers for Zombie Farm, and those changes are not guaranteed to be suitable for other games.

## Requirements

You need:

- A packaged touchHLE executable.
- Your own Zombie Farm / ZFR IPA file.
- The font assets in `touchHLE_fonts/`.

Use a short path without non-ASCII characters when possible, for example:

```text
D:\Games\touchHLE
C:\touchHLE
```

You can keep your IPA in a fixed folder such as:

```text
.\zombie_farm\ZFR.ipa
```

## Building On Windows

Windows builds require:

- Rust toolchain
- CMake
- Visual Studio 2022 Build Tools with the C++ build tools installed

Use the provided Windows build script:

```bat
.\build_windows.bat release
```

For a build that is only meant to run on the current PC, enable native CPU optimization:

```bat
.\build_windows.bat release native
```

This mode enables `target-cpu=native`, `opt-level=3`, `codegen-units=1`, and `lto=fat`, so the executable may not be suitable for other computers. Remove the `native` argument to turn it off.

For a build intended for a specific CPU family, pass the Rust/LLVM CPU name explicitly:

```bat
.\build_windows.bat release --cpu=raptorlake
.\build_windows.bat release --cpu=znver4
```

For example, Intel Core i9-14900K can use `--cpu=raptorlake`. For AMD systems, choose the target based on the recipient's CPU architecture, such as `znver3` for many Ryzen 5000 CPUs, and `znver4`/`znver5` for many Ryzen 7000/9000 CPUs. If you are not sure what the recipient supports, prefer the more compatible `--cpu=x86-64-v3`.

To check the local CPU model in PowerShell:

```powershell
Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name
```

To list CPU names supported by the current Rust toolchain:

```powershell
rustc -C target-cpu=help --target x86_64-pc-windows-msvc
```

For a debug build:

```bat
.\build_windows.bat debug
```

## Running On Windows

Open Command Prompt or PowerShell in the extracted touchHLE folder, then run:

```bat
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

If your IPA is somewhere else, replace the path with your actual file path:

```bat
.\touchHLE.exe "D:\Games\ZombieFarm\ZFR.ipa" --device-family="ipad"
```

Some versions can also be started with the default device mode:

```bat
.\touchHLE.exe ".\zombie_farm\Zombie_Farm_1.181.ipa"
```

## Player Name

An environment variable can override the current local player's Zombie Farm display name without changing the save file or replacing friends' names:

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME="Your Name"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

To clear the override:

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME
```

## Experimental public friend farms

This feature is disabled by default. Zombie Farm 1.0 enables the public friend API only when `TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL` is set. It uploads the current username and a `saveGame.bin2` snapshot to that server and allows the game to see every public farm stored there.

The experiment sends no passwords, cookies, tokens, or other authentication data. The server has no authentication at all: any client can choose any valid public player ID and username, view every uploaded farm, and overwrite an existing record by using the same public player ID. Do not use a username that needs protection, and do not put passwords, secrets, or private save data in these environment variables or requests.

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL="https://zombiefarm.aeutlook.com"
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME="Your Name"
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_ID="your_public_player_01"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

Setting `TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL` is enough to enable the online feature; the display name and public player ID are optional overrides. `TOUCHHLE_ZOMBIE_FARM_PLAYER_ID` is a public identifier, not a password. It accepts 1 to 80 ASCII letters, digits, `-`, or `_`. If omitted, touchHLE generates and persists a public ID for the current installation. The base URL may use `http://` or `https://` with a normally trusted certificate. Network requests have timeout fallbacks, so an unavailable server returns a failure instead of waiting forever. This feature is gated to Zombie Farm bundle `com.playforge.ZFR.LZ54D2GT3D`, version `1.0`.

To disable the online feature:

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL
```

## Time Offset

To shift the in-emulator time forward or backward, set an environment variable before launching the game.

This PowerShell example shifts the in-emulator time forward by 900 seconds, or 15 minutes:

```powershell
$env:TOUCHHLE_TIME_OFFSET_SECONDS="900"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

The setting only applies to the current PowerShell window. It disappears after you close that window.

To clear the time offset:

```powershell
Remove-Item Env:\TOUCHHLE_TIME_OFFSET_SECONDS
```

## Zombie Farm Invasion Cooldown

To keep Zombie Farm 1.0's robot-invasion cooldown ready, set this before launching:

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_NO_INVASION_COOLDOWN="1"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

This only overrides the `lastInvasionDate` interval read by the UI and invasion eligibility check. It does not change the stored date or bypass other invasion requirements such as the zombie-count requirement. It is gated to Zombie Farm bundle `com.playforge.ZFR.LZ54D2GT3D`, version `1.0`. The environment variable also accepts `true`, `yes`, or `on`, case-insensitively.

To disable this feature:

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_NO_INVASION_COOLDOWN
```

## Windows Shortcuts

These shortcuts are mainly for Zombie Farm debugging and troubleshooting:

- `F9`: Zombie Farm only. Quickly completes the current quest queue through the game's own logic and claims the rewards. Press it once after launching the game.
- `F10`: Toggles the visual UI element inspector. Hover with the mouse to inspect UIKit elements. Press `F10` again or press `Esc` to close it.
- `F11`: Dumps the current UI inspection information to the log. Useful for checking view hierarchy, tables, and control state.
- `F12`: Requests debugger entry. This only takes effect when touchHLE is connected to a debugger; otherwise it is ignored.

## Android Is Unsupported

The Android version is currently unsupported and should only be treated as experimental. Known limitations:

- The `TOUCHHLE_TIME_OFFSET_SECONDS` time offset environment variable cannot be used.
- Quest progress cannot be saved.
- The `F9` one-key quest completion shortcut is not available.

If you still want to try the Android version, place the IPA like this:

1. Install the Android APK.
2. Put the IPA file into the app data folder's `touchHLE_apps` directory.

For the default package name, the path is usually:

```text
/sdcard/Android/data/org.touchhle.android/files/touchHLE_apps
```

If you installed an APK with a branding suffix, the package name in this path may be different. Use the actual package name on your device.

3. Open touchHLE.
4. Select the IPA file in the app and start the game.

## Troubleshooting

### The executable is missing

Make sure you extracted the full Windows package. `touchHLE.exe` should be in the same folder as this README.

### The IPA path contains spaces

Wrap paths containing spaces in double quotes:

```bat
.\touchHLE.exe "D:\Games\ZombieFarm\ZFR 1.0.ipa" --device-family="ipad"
```

### iPad layout or assets look wrong

ZFR usually works best with the iPad device argument:

```bat
--device-family="ipad"
```

Full example:

```bat
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```
