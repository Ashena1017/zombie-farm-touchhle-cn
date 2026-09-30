/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Parsing and management of user-configurable options, e.g. for input methods.

use crate::gles::GLESImplementation;
use crate::window::{DeviceFamily, DeviceOrientation};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read};
use std::net::{SocketAddr, ToSocketAddrs};
use std::num::NonZeroU32;
use std::path::PathBuf;

pub const OPTIONS_HELP: &str =
    include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/OPTIONS_HELP.txt"));

/// Game controller button for `--button-to-touch=` option.
#[derive(Copy, Clone, Hash, PartialEq, Eq, Debug)]
pub enum Button {
    DPadLeft,
    DPadUp,
    DPadRight,
    DPadDown,
    Start,
    A,
    B,
    X,
    Y,
    LeftShoulder,
}

/// Parses a scale factor written as an integer ("2"), a decimal ("1.5") or a
/// fraction ("3/2"), returning it as a reduced numerator/denominator pair.
///
/// The scale hack is used both to size the window and to size the renderbuffer
/// the app draws into, so the two must agree exactly. Integers alone are too
/// coarse once the emulated screen is an iPad: 1024x768 is the only integer
/// multiple that fits a 2560x1440 display (x2 is 2048x1536, which does not),
/// which would leave the useful range empty. A rational keeps the arithmetic
/// exact, so e.g. 3/2 gives a 1536x1152 window with no rounding drift.
pub fn parse_scale_factor(value: &str) -> Option<(NonZeroU32, NonZeroU32)> {
    let value = value.trim();
    let (num_str, den_str) = match value.split_once('/') {
        Some((n, d)) => (n.trim(), Some(d.trim())),
        None => (value, None),
    };

    // Parse the numerator, allowing a decimal point, e.g. "1.5".
    let (num, den) = match num_str.split_once('.') {
        Some((whole, frac)) => {
            if frac.is_empty() || !frac.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let whole: u64 = if whole.is_empty() {
                0
            } else {
                whole.parse().ok()?
            };
            let frac_val: u64 = frac.parse().ok()?;
            let pow = 10u64.checked_pow(frac.len() as u32)?;
            (whole.checked_mul(pow)?.checked_add(frac_val)?, pow)
        }
        None => (num_str.parse().ok()?, 1),
    };

    let den: u64 = match den_str {
        Some(d) => d.parse().ok()?,
        None => den,
    };
    if num == 0 || den == 0 {
        return None;
    }

    // Reduce, so "2/2" and "1" describe the same window (and compare equal when
    // the app picker highlights the active choice).
    let g = gcd(num, den);
    let (num, den) = (num / g, den / g);
    Some((
        NonZeroU32::new(u32::try_from(num).ok()?)?,
        NonZeroU32::new(u32::try_from(den).ok()?)?,
    ))
}

fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        let t = a % b;
        a = b;
        b = t;
    }
    a.max(1)
}

/// Bounds and default for `--zf-wheel-zoom-step=`.
///
/// The value is the multiplicative step the mouse wheel applies to Zombie Farm's
/// farm-map zoom, i.e. one notch multiplies the current zoom by this much. The
/// bounds exist so a typo cannot make the wheel useless rather than merely odd:
/// a step of 1.0 or below would leave the zoom unchanged or invert the
/// direction, contradicting the documented "scroll away from you to zoom in",
/// and the 1.01 floor additionally keeps the wheel from moving the map by an
/// amount indistinguishable from not working. The upper bound stops a single
/// notch from jumping across the game's whole 0.2..2.0 zoom range.
///
/// They are inclusive and deliberately match the bounds the game-manager UI
/// offers, so a value the UI writes is always one touchHLE accepts and vice
/// versa.
pub const ZF_WHEEL_ZOOM_STEP_DEFAULT: f32 = 1.1;
pub const ZF_WHEEL_ZOOM_STEP_MIN: f32 = 1.01;
pub const ZF_WHEEL_ZOOM_STEP_MAX: f32 = 2.0;

/// Parses and range-checks a `--zf-wheel-zoom-step=` value.
pub fn parse_wheel_zoom_step(value: &str) -> Result<f32, String> {
    let step: f32 = value
        .trim()
        .parse()
        .map_err(|_| "Invalid value for --zf-wheel-zoom-step=".to_string())?;
    if !step.is_finite() {
        return Err("Value for --zf-wheel-zoom-step= must be a finite number".to_string());
    }
    if step < ZF_WHEEL_ZOOM_STEP_MIN || step > ZF_WHEEL_ZOOM_STEP_MAX {
        return Err(format!(
            "Value for --zf-wheel-zoom-step= must be between {} and {}",
            ZF_WHEEL_ZOOM_STEP_MIN, ZF_WHEEL_ZOOM_STEP_MAX
        ));
    }
    Ok(step)
}

/// Scales `v` by `num/den`, rounding to nearest. Used for every dimension the
/// scale hack affects so the window, the renderbuffer and the viewport all agree.
pub fn scale_dim(v: u32, num: u32, den: u32) -> u32 {
    ((v as u64 * num as u64 + den as u64 / 2) / den as u64) as u32
}

/// Inverse of [scale_dim].
pub fn unscale_dim(v: u32, num: u32, den: u32) -> u32 {
    ((v as u64 * den as u64 + num as u64 / 2) / num as u64) as u32
}

/// Signed counterpart of [scale_dim], for viewport/scissor coordinates, which
/// may legitimately be negative. Rounds away from zero so a negative offset
/// stays at least as large in magnitude as the unscaled one.
pub fn scale_dim_i(v: i32, num: u32, den: u32) -> i32 {
    let scaled = (v as i64 * num as i64) as f64 / den as f64;
    scaled.round() as i32
}

/// Struct containing all user-configurable options.
#[derive(Clone)]
pub struct Options {
    pub fullscreen: bool,
    pub device_family: Option<DeviceFamily>,
    pub initial_orientation: DeviceOrientation,
    /// Numerator of the scale hack factor (see [Options::scale_hack_den]).
    pub scale_hack: NonZeroU32,
    /// Denominator of the scale hack factor. 1 for a plain integer scale.
    pub scale_hack_den: NonZeroU32,
    /// Overrides the emulated screen size, in the portrait orientation (the
    /// same convention as [DeviceFamily::portrait_size]). `None` means the size
    /// comes from `device_family` as usual.
    pub device_size: Option<(u32, u32)>,
    pub deadzone: f32,
    pub analog_stick_tilt_controls: bool,
    pub x_tilt_range: f32,
    pub y_tilt_range: f32,
    pub x_tilt_offset: f32,
    pub y_tilt_offset: f32,
    pub button_to_touch: HashMap<Button, (f32, f32)>,
    pub dpad_to_touch: Option<(f32, f32, f32, f32)>,
    pub stick_to_touch: Option<(f32, f32, f32, f32)>,
    pub stabilize_virtual_cursor: Option<(f32, f32)>,
    pub gles1_implementation: Option<GLESImplementation>,
    pub direct_memory_access: bool,
    pub gdb_listen_addrs: Option<Vec<SocketAddr>>,
    pub preferred_languages: Option<Vec<String>>,
    pub headless: bool,
    pub quiet_game_stdout: bool,
    pub zfr_profile: bool,
    /// Multiplicative step the mouse wheel applies to the Zombie Farm farm-map
    /// zoom, per notch. See [ZF_WHEEL_ZOOM_STEP_DEFAULT].
    pub zf_wheel_zoom_step: f32,
    pub print_fps: bool,
    pub fps_limit: Option<f64>,
    pub non_blocking_zero_timeout_run_loop: bool,
    pub force_composition: bool,
    pub network_access: bool,
    pub popup_errors: bool,
    pub dumping_options: DumpingOptions,
    pub dumping_file: PathBuf,
    pub ignore_gl_errors: bool,
    pub zero_stack_after_guest_to_host_call: Option<u32>,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            fullscreen: false,
            device_family: None,
            initial_orientation: DeviceOrientation::Portrait,
            scale_hack: NonZeroU32::new(1).unwrap(),
            scale_hack_den: NonZeroU32::new(1).unwrap(),
            device_size: None,
            analog_stick_tilt_controls: true,
            deadzone: 0.1,
            x_tilt_range: 60.0,
            y_tilt_range: 60.0,
            x_tilt_offset: 0.0,
            y_tilt_offset: 0.0,
            button_to_touch: HashMap::new(),
            dpad_to_touch: None,
            stick_to_touch: None,
            stabilize_virtual_cursor: None,
            gles1_implementation: None,
            direct_memory_access: true,
            gdb_listen_addrs: None,
            preferred_languages: None,
            headless: false,
            quiet_game_stdout: false,
            zfr_profile: false,
            zf_wheel_zoom_step: ZF_WHEEL_ZOOM_STEP_DEFAULT,
            print_fps: false,
            fps_limit: Some(60.0), // Original iPhone is 60Hz and uses v-sync,
            non_blocking_zero_timeout_run_loop: false,
            force_composition: false,
            network_access: false,
            popup_errors: true,
            dumping_options: Default::default(),
            dumping_file: crate::paths::user_data_base_path().join("DUMP.txt"),
            ignore_gl_errors: false,
            zero_stack_after_guest_to_host_call: None,
        }
    }
}

impl Options {
    /// Parse the command-line argument syntax for an option. Returns `Ok(true)`
    /// if the option was valid and has been applied, or `Ok(false)` if the
    /// option was not recognized.
    pub fn parse_argument(&mut self, arg: &str) -> Result<bool, String> {
        fn parse_degrees(arg: &str, name: &str) -> Result<f32, String> {
            let arg: f32 = arg
                .parse()
                .map_err(|_| format!("Value for {name} is invalid"))?;
            if !arg.is_finite() || !(-360.0..=360.0).contains(&arg) {
                return Err(format!("Value for {name} is out of range"));
            }
            Ok(arg)
        }

        if arg == "--fullscreen" {
            self.fullscreen = true;
        } else if arg == "--landscape-left" {
            self.initial_orientation = DeviceOrientation::LandscapeLeft;
        } else if arg == "--landscape-right" {
            self.initial_orientation = DeviceOrientation::LandscapeRight;
        } else if let Some(value) = arg.strip_prefix("--device-family=") {
            let parsed =
                DeviceFamily::try_from(value).map_err(|_| "Invalid device family".to_string())?;
            self.device_family = Some(parsed);
        } else if let Some(value) = arg.strip_prefix("--scale-hack=") {
            let (num, den) = parse_scale_factor(value)
                .ok_or_else(|| "Invalid scale hack factor".to_string())?;
            self.scale_hack = num;
            self.scale_hack_den = den;
        } else if let Some(value) = arg.strip_prefix("--device-size=") {
            // Overrides the emulated screen size outright, instead of deriving it
            // from --device-family. The value is written the way screen
            // resolutions normally are - width x height, wide side first - e.g.
            // 1280x720. It is normalised to the portrait convention used by
            // DeviceFamily::portrait_size (short side first) so the existing
            // orientation-swapping logic keeps working. Use this for arbitrary
            // aspect ratios (e.g. 16:9) that no device-family/scale-hack
            // combination can produce.
            let (width, height) = value
                .split_once(['x', 'X'])
                .ok_or_else(|| "--device-size= requires WIDTHxHEIGHT".to_string())?;
            let width: u32 = width
                .parse()
                .map_err(|_| "Invalid width for --device-size=".to_string())?;
            let height: u32 = height
                .parse()
                .map_err(|_| "Invalid height for --device-size=".to_string())?;
            if width == 0 || height == 0 || width > 8192 || height > 8192 {
                return Err("--device-size= dimensions must be between 1 and 8192".to_string());
            }
            self.device_size = Some((width.min(height), width.max(height)));
        } else if arg == "--disable-analog-stick-tilt-controls" {
            self.analog_stick_tilt_controls = false;
        } else if let Some(value) = arg.strip_prefix("--deadzone=") {
            self.deadzone = parse_degrees(value, "deadzone")?;
        } else if let Some(value) = arg.strip_prefix("--x-tilt-range=") {
            self.x_tilt_range = parse_degrees(value, "X tilt range")?;
        } else if let Some(value) = arg.strip_prefix("--y-tilt-range=") {
            self.y_tilt_range = parse_degrees(value, "Y tilt range")?;
        } else if let Some(value) = arg.strip_prefix("--x-tilt-offset=") {
            self.x_tilt_offset = parse_degrees(value, "X tilt offset")?;
        } else if let Some(value) = arg.strip_prefix("--y-tilt-offset=") {
            self.y_tilt_offset = parse_degrees(value, "Y tilt offset")?;
        } else if let Some(values) = arg.strip_prefix("--button-to-touch=") {
            let (button, coords) = values
                .split_once(',')
                .ok_or_else(|| "--button-to-touch= requires three values".to_string())?;
            let (x, y) = coords
                .split_once(',')
                .ok_or_else(|| "--button-to-touch= requires three values".to_string())?;
            let button = match button {
                "DPadLeft" => Ok(Button::DPadLeft),
                "DPadUp" => Ok(Button::DPadUp),
                "DPadRight" => Ok(Button::DPadRight),
                "DPadDown" => Ok(Button::DPadDown),
                "Start" => Ok(Button::Start),
                "A" => Ok(Button::A),
                "B" => Ok(Button::B),
                "X" => Ok(Button::X),
                "Y" => Ok(Button::Y),
                "LeftShoulder" => Ok(Button::LeftShoulder),
                _ => Err("Invalid button for --button-to-touch=".to_string()),
            }?;
            let x: f32 = x
                .parse()
                .map_err(|_| "Invalid X co-ordinate for --button-to-touch=".to_string())?;
            let y: f32 = y
                .parse()
                .map_err(|_| "Invalid Y co-ordinate for --button-to-touch=".to_string())?;
            self.button_to_touch.insert(button, (x, y));
        } else if let Some(values) = arg.strip_prefix("--stick-to-touch=") {
            let nums: [f32; 4] = values
                .split(',')
                .map(|s| s.parse::<f32>())
                .collect::<Result<Vec<_>, _>>()
                .map_err(|_| "invalid --stick-to-touch".to_string())?
                .try_into()
                .map_err(|_| "--stick-to-touch= requires four values".to_string())?;

            self.stick_to_touch = Some((nums[0], nums[1], nums[2], nums[3]));
        } else if let Some(values) = arg.strip_prefix("--dpad-to-touch=") {
            let nums: [f32; 4] = values
                .split(',')
                .map(|s| s.parse::<f32>())
                .collect::<Result<Vec<_>, _>>()
                .map_err(|_| "invalid --dpad-to-touch".to_string())?
                .try_into()
                .map_err(|_| "--dpad-to-touch= requires four values".to_string())?;

            self.dpad_to_touch = Some((nums[0], nums[1], nums[2], nums[3]));
        } else if let Some(value) = arg.strip_prefix("--stabilize-virtual-cursor=") {
            let (smoothing_strength, sticky_radius) = value
                .split_once(',')
                .ok_or_else(|| "--stabilize-virtual-cursor= requires two values".to_string())?;
            let smoothing_strength: f32 = smoothing_strength
                .parse()
                .ok()
                .and_then(|s| if s < 0.0 { None } else { Some(s) })
                .ok_or_else(|| {
                    "Invalid smoothing strength for --stabilize-virtual-cursor=".to_string()
                })?;
            let sticky_radius: f32 = sticky_radius
                .parse()
                .ok()
                .and_then(|s| if s < 0.0 { None } else { Some(s) })
                .ok_or_else(|| {
                    "Invalid sticky radius for --stabilize-virtual-cursor=".to_string()
                })?;
            self.stabilize_virtual_cursor = Some((smoothing_strength, sticky_radius));
        } else if let Some(value) = arg.strip_prefix("--gles1=") {
            self.gles1_implementation = Some(
                GLESImplementation::from_short_name(value)
                    .map_err(|_| "Unrecognized --gles1= value".to_string())?,
            );
        } else if arg == "--disable-direct-memory-access" {
            self.direct_memory_access = false;
        } else if let Some(address) = arg.strip_prefix("--gdb=") {
            let addrs = address
                .to_socket_addrs()
                .map_err(|e| format!("Could not resolve GDB server listen address: {e}"))?
                .collect();
            self.gdb_listen_addrs = Some(addrs);
        } else if let Some(value) = arg.strip_prefix("--preferred-languages=") {
            self.preferred_languages = Some(value.split(',').map(ToOwned::to_owned).collect());
        } else if arg == "--headless" {
            self.headless = true;
            // Can't show the dialog box when headless!
            self.popup_errors = false;
        } else if arg == "--quiet-game-stdout" {
            self.quiet_game_stdout = true;
        } else if arg == "--zfr-profile" {
            self.zfr_profile = true;
        } else if let Some(value) = arg.strip_prefix("--zf-wheel-zoom-step=") {
            self.zf_wheel_zoom_step = parse_wheel_zoom_step(value)?;
        } else if arg == "--print-fps" {
            self.print_fps = true;
        } else if let Some(value) = arg.strip_prefix("--fps-limit=") {
            if value == "off" {
                self.fps_limit = None;
            } else {
                let limit: f64 = value
                    .parse()
                    .ok()
                    .and_then(|v| if v <= 0.0 { None } else { Some(v) })
                    .ok_or_else(|| "Invalid value for --fps-limit=".to_string())?;
                self.fps_limit = Some(limit);
            }
        } else if arg == "--non-blocking-zero-timeout-run-loop" {
            self.non_blocking_zero_timeout_run_loop = true;
        } else if arg == "--force-composition" {
            self.force_composition = true;
        } else if arg == "--allow-network-access" {
            self.network_access = true;
        } else if arg == "--no-error-popup" {
            self.popup_errors = false;
        } else if let Some(values) = arg.strip_prefix("--dump=") {
            self.dumping_options = parse_dump_options(values)?;
        } else if let Some(path) = arg.strip_prefix("--dump-file=") {
            self.dumping_file = crate::paths::user_data_base_path().join(path);
        } else if arg == "--ignore-gl-errors" {
            self.ignore_gl_errors = true;
        } else if let Some(value) = arg.strip_prefix("--zero-stack-after-guest-to-host-call=") {
            self.zero_stack_after_guest_to_host_call = Some(value.parse().map_err(|_| {
                "Invalid value for --zero-stack-after-guest-to-host-call=".to_string()
            })?);
        } else {
            return Ok(false);
        };
        Ok(true)
    }
}

/// Try to get app-specific options from a file.
///
/// Returns [Ok] if there is no error when reading the file, otherwise [Err].
/// The [Ok] value is a [Some] with the options if they could be found, or
/// [None] if no options were found for this app.
pub fn get_options_from_file<F: Read>(file: F, app_id: &str) -> Result<Option<String>, String> {
    let file = BufReader::new(file);
    for (line_no, line) in BufRead::lines(file).enumerate() {
        // Line numbering usually starts from 1
        let line_no = line_no + 1;

        let line = line.map_err(|e| format!("Error while reading line {line_no}: {e}"))?;

        // # for single-line comments
        let line = if let Some((rest, _)) = line.split_once('#') {
            rest
        } else {
            &line
        };

        // Empty/all-comment lines ignored
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let (line_app_id, line_options) = line.split_once(':').ok_or_else(|| format!("Line {line_no} is not a comment and is missing a colon (:) to separate the app ID from the options"))?;
        let line_app_id = line_app_id.trim();

        if line_app_id != app_id {
            continue;
        }

        let line_options = line_options.trim();
        if line_options.is_empty() {
            return Ok(None);
        } else {
            return Ok(Some(line_options.to_string()));
        }
    }
    Ok(None)
}

#[derive(Default, Clone)]
pub struct DumpingOptions {
    pub linking_info: bool,
    pub symbols: bool,
}

impl DumpingOptions {
    /// Check if any of the dumping options are active.
    pub fn any(&self) -> bool {
        self.linking_info || self.symbols
    }
}

fn parse_dump_options(options: &str) -> Result<DumpingOptions, String> {
    let mut dumping_options = DumpingOptions::default();
    for opt in options.split(",") {
        if opt == "linking-info" {
            // Dumps linked symbols, classes and selectors for the given app
            dumping_options.linking_info = true;
        } else if opt == "symbols" {
            // Dumps touchHLE provided symbols and exits
            dumping_options.symbols = true;
        } else {
            return Err(format!("Unrecognized option {opt} for --dump=..."));
        }
    }
    Ok(dumping_options)
}
