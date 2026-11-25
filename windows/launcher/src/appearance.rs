use crate::{bridge::Result, win};
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Appearance {
    pub theme: String,
    accent: String,
    custom: String,
    is_custom: bool,
}

impl Appearance {
    fn valid(&self) -> bool {
        let valid_color = |value: &str| {
            value.len() == 7
                && value.starts_with('#')
                && value.as_bytes()[1..].iter().all(u8::is_ascii_hexdigit)
        };
        matches!(self.theme.as_str(), "light" | "dark" | "system")
            && valid_color(&self.accent)
            && valid_color(&self.custom)
    }

    pub fn load(root: &Path) -> Self {
        let stored = fs::read(root.join("launcher_appearance.json"))
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Self>(&bytes).ok())
            .filter(Self::valid);
        stored.unwrap_or_else(|| {
            let legacy =
                fs::read_to_string(root.join("launcher_night_mode.txt")).unwrap_or_default();
            let theme = match legacy.trim_start_matches('\u{feff}').trim() {
                "1" => "dark",
                "0" => "light",
                _ => "system",
            };
            Self {
                theme: theme.into(),
                accent: "#B57B98".into(),
                custom: "#B57B98".into(),
                is_custom: false,
            }
        })
    }

    pub fn save(&self, root: &Path) -> Result<()> {
        if !self.valid() {
            return Err("主题或颜色值无效。".into());
        }
        fs::create_dir_all(root).map_err(|e| e.to_string())?;
        let tmp = root.join(format!(".launcher_appearance-{}.tmp", std::process::id()));
        let contents = serde_json::to_vec(self).map_err(|e| e.to_string())?;
        fs::write(&tmp, contents).map_err(|e| format!("保存外观失败：{e}"))?;
        let result = win::replace_file(&tmp, &root.join("launcher_appearance.json"));
        if result.is_err() {
            let _ = fs::remove_file(&tmp);
        }
        result
    }

    pub fn native_theme(&self) -> Option<tauri::Theme> {
        match self.theme.as_str() {
            "dark" => Some(tauri::Theme::Dark),
            "light" => Some(tauri::Theme::Light),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn with_install(name: &str, test: impl FnOnce(&Path)) {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "zf-appearance-{name}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        test(&root);
        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn first_open_uses_system_theme_and_dusty_rose() {
        with_install("first", |root| {
            let first = Appearance::load(root);
            assert_eq!(first.theme, "system");
            assert_eq!(first.accent, "#B57B98");
            assert!(!first.is_custom);
            assert_eq!(first.native_theme(), None);
        });
    }

    #[test]
    fn new_preferences_override_the_old_night_switch_after_restart() {
        with_install("migration", |root| {
            let legacy = root.join("launcher_night_mode.txt");
            fs::write(&legacy, "\u{feff}0\r\n").unwrap();
            assert_eq!(Appearance::load(root).theme, "light");
            fs::write(&legacy, "1").unwrap();
            let mut chosen = Appearance::load(root);
            assert_eq!(chosen.native_theme(), Some(tauri::Theme::Dark));

            chosen.theme = "system".into();
            chosen.accent = "#215C5C".into();
            chosen.custom.clone_from(&chosen.accent);
            chosen.is_custom = true;
            chosen.save(root).unwrap();
            let reopened = Appearance::load(root);
            assert_eq!(reopened.theme, "system");
            assert_eq!(reopened.accent, "#215C5C");
            assert_eq!(reopened.custom, "#215C5C");
            assert!(reopened.is_custom);

            chosen.theme = "light".into();
            chosen.save(root).unwrap();
            assert_eq!(Appearance::load(root).theme, "light");
        });
    }

    #[test]
    fn corrupt_preferences_fall_back_and_invalid_edits_preserve_the_file() {
        with_install("corrupt", |root| {
            let path = root.join("launcher_appearance.json");
            fs::write(&path, "{").unwrap();
            assert_eq!(Appearance::load(root).theme, "system");
            fs::write(root.join("launcher_night_mode.txt"), "0").unwrap();
            fs::write(
                &path,
                r##"{"theme":"dark","accent":"#ZZZZZZ","custom":"#B57B98","isCustom":false}"##,
            )
            .unwrap();
            let mut prefs = Appearance::load(root);
            assert_eq!(prefs.theme, "light");
            prefs.save(root).unwrap();
            let before = fs::read(&path).unwrap();
            prefs.theme = "invalid".into();
            assert!(prefs.save(root).is_err());
            assert_eq!(fs::read(path).unwrap(), before);
        });
    }
}
