/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */
//! Offline purchases for the nine original paid farmer appearances.

use super::*;

const PRICE: i32 = 15;
const BRAINS: i32 = 1;
const ALERT_TAG: i32 = 0x5a46_0015;

#[derive(Clone, Copy, Debug)]
struct Head { mask: i32, selection: &'static str }

fn product_head(product: &str) -> Option<Head> {
    let suffix = product.strip_prefix("com.playforge.ZombieFarm.FarmerHead")?;
    let number = suffix.strip_suffix("_iPad").unwrap_or(suffix);
    let selections = ["skeletonHeadMaleSelected:", "vampireHeadMaleSelected:",
        "skeletonHeadFemaleSelected:", "vampireHeadFemaleSelected:",
        "zombieHeadMaleSelected:", "zombieHeadFemaleSelected:",
        "paperBagHeadMaleSelected:", "monolithHeadMaleSelected:", "pumpkinHeadMaleSelected:"];
    let index = match number { "1" => 0, "2" => 1, "3" => 2, "4" => 3, "5" => 4,
        "6" => 5, "7" => 6, "8" => 7, "9" => 8, _ => return None };
    Some(Head { mask: 1 << index, selection: selections[index] })
}

fn supported(env: &Environment) -> bool {
    env.bundle.bundle_identifier() == "com.playforge.ZombieFarm.ZFR"
        && env.bundle.bundle_version() == "1.0"
}

struct Pending { menu: u32, game_data: u32, head: Head }
static PENDING: OnceLock<Mutex<HashMap<u32, Pending>>> = OnceLock::new();

fn pending() -> &'static Mutex<HashMap<u32, Pending>> {
    PENDING.get_or_init(|| Mutex::new(HashMap::new()))
}

fn forget(alert: id) -> Option<Pending> {
    pending().lock().unwrap().remove(&alert.to_bits())
}

fn release_pending(env: &mut Environment, p: Pending) {
    release(env, id::from_bits(p.menu));
    release(env, id::from_bits(p.game_data));
}

fn inform(env: &mut Environment, gui: id, title: &str, message: &str) {
    let title = ns_string::from_rust_string(env, title.to_string());
    let message = ns_string::from_rust_string(env, message.to_string());
    let _: id = msg![env; gui displayAlertSimple:title withMessage:message withSprite:nil];
    release(env, title);
    release(env, message);
}

fn select(env: &mut Environment, menu: id, head: Head) {
    let selector = env.objc.lookup_selector(head.selection).unwrap();
    let _: () = msg_send_no_type_checking(env, (menu, selector, nil));
}

pub(super) fn pre_dispatch(env: &mut Environment, receiver: id, selector: &str) -> bool {
    if !matches!(selector, "buyHead:" | "requestProductData" | "alertWindow:dismissedPositive:" | "dealloc") {
        return false;
    }
    if !supported(env) { return false; }

    if selector == "dealloc" {
        if let Some(p) = forget(receiver) {
            let regs = *env.cpu.regs();
            release_pending(env, p);
            env.cpu.regs_mut().copy_from_slice(&regs);
        }
        return false;
    }

    if selector == "alertWindow:dismissedPositive:"
        && zombie_farm_object_class_name(env, receiver) == Some("ZFGuiLayer")
    {
        let alert = id::from_bits(env.cpu.regs()[2]);
        let accepted = env.cpu.regs()[3] & 0xff != 0;
        let Some(p) = forget(alert) else {
            // A duplicate dismissal belongs to this dialog, too. Do not send
            // it into unrelated tutorial/market confirmation handling.
            if zombie_farm_object_class_name(env, alert) == Some("ZFAlertWindow") {
                let regs = *env.cpu.regs();
                let tag: i32 = msg![env; alert idTag];
                env.cpu.regs_mut().copy_from_slice(&regs);
                return tag == ALERT_TAG;
            }
            return false;
        };
        if accepted {
            let state: id = msg_class![env; GameState gameState];
            let data: id = msg![env; state zfGameData];
            if data.to_bits() == p.game_data {
                let flags: i32 = msg![env; data fflags];
                if flags & p.head.mask != 0 {
                    select(env, id::from_bits(p.menu), p.head);
                } else {
                    // Recheck at confirmation; cancellation and repeated callbacks
                    // never spend brains. Use the game's normal currency API.
                    let paid: bool = msg![env; state subResource:BRAINS amount:PRICE];
                    if paid {
                        let _: () = msg![env; data setFflags:(flags | p.head.mask)];
                        select(env, id::from_bits(p.menu), p.head);
                        let _: () = msg![env; state saveGame];
                        let _: () = msg![env; receiver updateBrains];
                        log!("ZombieFarm: purchased farmer flag 0x{:x} for {} brains", p.head.mask, PRICE);
                    } else {
                        inform(env, receiver, "脑子不足", "购买这位农场主需要15脑子。");
                    }
                }
            }
        }
        release_pending(env, p);
        env.cpu.regs_mut()[0] = 0;
        return true;
    }

    if zombie_farm_object_class_name(env, receiver) != Some("ZFFarmerSelectionMenu") {
        return false;
    }
    if selector == "requestProductData" {
        // Prices and purchases are local; the retired store has no role here.
        env.cpu.regs_mut()[0] = 0;
        return true;
    }
    if selector != "buyHead:" { return false; }
    let product = id::from_bits(env.cpu.regs()[2]);
    if product == nil { return false; }
    let Some(head) = product_head(&ns_string::to_rust_string(env, product)) else { return false; };
    let state: id = msg_class![env; GameState gameState];
    let data: id = msg![env; state zfGameData];
    if data == nil { return true; }
    let flags: i32 = msg![env; data fflags];
    if flags & head.mask != 0 {
        select(env, receiver, head);
        return true;
    }
    // Prevent two dialogs from buying different heads through the same menu.
    if pending().lock().unwrap().values().any(|p| p.menu == receiver.to_bits()) {
        return true;
    }
    if let Some(gui) = zombie_farm_get_gui_layer(env) {
        let enough: bool = msg![env; state hasResource:BRAINS amount:PRICE];
        if enough {
            let title = ns_string::from_rust_string(env, "购买农场主".to_string());
            let message = ns_string::from_rust_string(env, "花费15脑子永久解锁这位农场主？".to_string());
            let alert: id = msg![env; gui displayAlertSimpleChoice:title withMessage:message withSprite:nil];
            release(env, title);
            release(env, message);
            if alert != nil {
                retain(env, receiver);
                retain(env, data);
                pending().lock().unwrap().insert(alert.to_bits(), Pending {
                    menu: receiver.to_bits(), game_data: data.to_bits(), head,
                });
                let _: () = msg![env; alert setIdTag:ALERT_TAG];
                let _: () = msg![env; alert setDelegate:gui];
            }
        } else {
            inform(env, gui, "脑子不足", "购买这位农场主需要15脑子。");
        }
    }
    env.cpu.regs_mut()[0] = 0;
    true
}

pub(super) fn post_dispatch(env: &mut Environment, menu: id, selector: &str, args: &[u32; 16]) {
    if !supported(env) || selector != "table:cellTouched:"
        || zombie_farm_object_class_name(env, menu) != Some("ZFFarmerSelectionMenu") { return; }
    let cell = id::from_bits(args[3]);
    if zombie_farm_object_class_name(env, cell) != Some("ZFFarmerCell") { return; }
    let regs = *env.cpu.regs();
    let available: bool = msg![env; cell available];
    if !available {
        let label: id = msg![env; menu buttonText];
        let text = ns_string::from_rust_string(env, "15脑子购买".to_string());
        let _: () = msg![env; label setString:text];
        release(env, text);
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_nine_products_have_distinct_persistent_flags_for_both_devices() {
        let mut flags = 0;
        for number in 1..=9 {
            for suffix in ["", "_iPad"] {
                let head = product_head(&format!("com.playforge.ZombieFarm.FarmerHead{number}{suffix}")).unwrap();
                assert_eq!(head.mask, 1 << (number - 1));
                assert!(head.selection.ends_with("Selected:"));
                flags |= head.mask;
            }
        }
        assert_eq!(flags, 0x1ff);
        for product in ["com.playforge.ZombieFarm.FarmerHead0", "com.playforge.ZombieFarm.FarmerHead10",
            "com.playforge.ZombieFarm.FarmerHead1_extra", "other.FarmerHead1"] {
            assert!(product_head(product).is_none());
        }
    }
}
