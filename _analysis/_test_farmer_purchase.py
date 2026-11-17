"""Exercise production farmer hooks against a small, stateful guest API model.

This checks dialog ownership, cancellation, balance changes, persistent flags,
save calls and argument/register handling. It does not claim to test game UI.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '_analysis/dumps/farmer-scroll-20261117'
SOURCE = ROOT / 'touchHLE/touchHLE-fork/src/objc/messages/zombie_farm/farmers.rs'

HARNESS = r'''
#![allow(non_camel_case_types, non_upper_case_globals, dead_code)]
use std::{collections::HashMap, sync::{Mutex, OnceLock}};
#[derive(Clone,Copy,Debug,PartialEq,Eq,Hash)] struct id(u32);
impl id { fn from_bits(v:u32)->Self {Self(v)} fn to_bits(self)->u32 {self.0} }
const nil:id=id(0);
#[derive(Default)] struct Cpu { regs:[u32;16] }
impl Cpu {fn regs(&self)->&[u32;16] {&self.regs} fn regs_mut(&mut self)->&mut[u32;16] {&mut self.regs}}
struct Bundle {identifier:&'static str}
impl Bundle {fn bundle_identifier(&self)->&str {self.identifier} fn bundle_version(&self)->&str {"1.0"}}
struct ObjC;
impl ObjC {fn lookup_selector(&self,s:&str)->Option<&'static str> {
  Some(match s {"skeletonHeadMaleSelected:"=>"skeletonHeadMaleSelected:","pumpkinHeadMaleSelected:"=>"pumpkinHeadMaleSelected:",_=>panic!("unexpected selection {s}")})
}}
struct Environment {cpu:Cpu,bundle:Bundle,objc:ObjC,strings:HashMap<u32,String>,next:u32,
  brains:i32,flags:i32,active_data:id,menu_class:&'static str,alerts:HashMap<u32,i32>,
  refs:HashMap<u32,i32>,last_alert:id,transactions:usize,saves:Vec<(i32,i32)>,
  selections:Vec<&'static str>,available:bool,label:String,shown_messages:Vec<String>}
fn fixture()->Environment {
  production::reset();
  Environment {cpu:Cpu::default(),bundle:Bundle {identifier:"com.playforge.ZombieFarm.ZFR"},objc:ObjC,
    strings:HashMap::new(),next:1000,brains:30,flags:0x4000,active_data:id(2),menu_class:"ZFFarmerSelectionMenu",
    alerts:HashMap::new(),refs:HashMap::new(),last_alert:nil,transactions:0,saves:vec![],selections:vec![],available:false,label:"购买".into(),shown_messages:vec![]}
}
mod ns_string {
 use super::*;
 pub fn from_rust_string(e:&mut Environment,s:String)->id {let a=e.next;e.next+=1;e.strings.insert(a,s);e.refs.insert(a,1);id(a)}
 pub fn to_rust_string(e:&Environment,a:id)->String {e.strings[&a.0].clone()}
}
fn retain(e:&mut Environment,a:id) { *e.refs.entry(a.0).or_default()+=1; }
fn release(e:&mut Environment,a:id) { *e.refs.entry(a.0).or_default()-=1;e.cpu.regs[0]=0xdead; }
fn zombie_farm_object_class_name(e:&Environment,a:id)->Option<&str> {
 match a.0 {3=>Some("ZFGuiLayer"),4=>Some(e.menu_class),5=>Some("ZFFarmerCell"),
  x if e.alerts.contains_key(&x)=>Some("ZFAlertWindow"),_=>None}
}
fn zombie_farm_get_gui_layer(_:&mut Environment)->Option<id> {Some(id(3))}
fn msg_send_no_type_checking(e:&mut Environment,args:(id,&'static str,id)) {
 assert_eq!(args.0,id(4));assert_eq!(args.2,nil);e.selections.push(args.1);
}
fn show(e:&mut Environment,message:id,choice:bool)->id {
 e.shown_messages.push(e.strings[&message.0].clone());
 if !choice {return nil;}
 let a=id(e.next);e.next+=1;e.alerts.insert(a.0,0);e.last_alert=a;a
}
fn pay(e:&mut Environment,resource:i32,amount:i32)->bool {
 assert_eq!((resource,amount),(1,15));
 if e.brains<amount {return false;} e.brains-=amount;e.transactions+=1;true
}
macro_rules! log {($($t:tt)*)=>{{let _=format!($($t)*);}}}
macro_rules! msg_class {($e:ident; GameState gameState)=>{id(1)}}
macro_rules! msg {
 ($e:ident; $r:ident zfGameData)=>{{$e.active_data}};
 ($e:ident; $r:ident fflags)=>{{$e.flags}};
 ($e:ident; $r:ident setFflags:$v:expr)=>{{$e.flags=$v;}};
 ($e:ident; $r:ident subResource:$v:ident amount:$n:ident)=>{{pay($e,$v,$n)}};
 ($e:ident; $r:ident hasResource:$v:ident amount:$n:ident)=>{{assert_eq!(($v,$n),(1,15));$e.brains >= $n}};
 ($e:ident; $r:ident saveGame)=>{{$e.saves.push(($e.brains,$e.flags));}};
 ($e:ident; $r:ident updateBrains)=>{{}};
 ($e:ident; $r:ident displayAlertSimple:$t:ident withMessage:$m:ident withSprite:nil)=>{{show($e,$m,false)}};
 ($e:ident; $r:ident displayAlertSimpleChoice:$t:ident withMessage:$m:ident withSprite:nil)=>{{show($e,$m,true)}};
 ($e:ident; $r:ident setDelegate:$v:ident)=>{{assert_eq!($v,id(3));}};
 ($e:ident; $r:ident setIdTag:$v:ident)=>{{$e.alerts.insert($r.0,$v);}};
 ($e:ident; $r:ident idTag)=>{{$e.alerts[&$r.0]}};
 ($e:ident; $r:ident available)=>{{$e.available}};
 ($e:ident; $r:ident buttonText)=>{{id(6)}};
 ($e:ident; $r:ident setString:$v:ident)=>{{$e.label=$e.strings[&$v.0].clone();}};
}
mod production {
 use super::*;
 // SOURCE
 pub(super) fn reset() {pending().lock().unwrap().clear();}
 pub(super) fn begin(e:&mut Environment,product:&str)->bool {
   let p=ns_string::from_rust_string(e,product.to_string());e.cpu.regs[2]=p.0;
   pre_dispatch(e,id(4),"buyHead:")
 }
 pub(super) fn confirm(e:&mut Environment,accepted:bool)->bool {
   e.cpu.regs[2]=e.last_alert.0;e.cpu.regs[3]=accepted as u32;
   pre_dispatch(e,id(3),"alertWindow:dismissedPositive:")
 }
 pub(super) fn destroyed(e:&mut Environment) {let a=e.last_alert;assert!(!pre_dispatch(e,a,"dealloc"));}
 pub(super) fn label(e:&mut Environment) {
   let mut args=[0;16];args[3]=5;post_dispatch(e,id(4),"table:cellTouched:",&args);
 }
}
use production::*;
const PRODUCT:&str="com.playforge.ZombieFarm.FarmerHead1";
#[test] fn purchase_spends_exactly_fifteen_and_saves_unlock_without_changing_other_flags() {
 let mut e=fixture();assert!(begin(&mut e,PRODUCT));assert_eq!(e.brains,30);assert!(e.saves.is_empty());
 assert!(confirm(&mut e,true));assert_eq!((e.brains,e.flags),(15,0x4001));assert_eq!(e.saves,[(15,0x4001)]);
 assert_eq!(e.selections,["skeletonHeadMaleSelected:"]);assert_eq!(e.refs[&4],0);assert_eq!(e.refs[&2],0);
 assert!(confirm(&mut e,true));assert_eq!(e.transactions,1);assert_eq!(e.saves.len(),1);
}
#[test] fn cancellation_never_spends_or_unlocks_and_releases_dialog_owners() {
 let mut e=fixture();begin(&mut e,PRODUCT);assert!(confirm(&mut e,false));
 assert_eq!((e.brains,e.flags),(30,0x4000));assert!(e.selections.is_empty());assert!(e.saves.is_empty());
 assert_eq!(e.refs[&4],0);assert_eq!(e.refs[&2],0);
}
#[test] fn insufficient_balance_before_and_after_confirmation_does_not_unlock() {
 let mut e=fixture();e.brains=14;begin(&mut e,PRODUCT);assert_eq!(e.last_alert,nil);assert_eq!(e.transactions,0);
 assert!(e.shown_messages.last().unwrap().contains("15"));
 let mut e=fixture();begin(&mut e,PRODUCT);e.brains=14;confirm(&mut e,true);
 assert_eq!((e.brains,e.flags),(14,0x4000));assert!(e.saves.is_empty());
}
#[test] fn exact_balance_is_accepted_and_an_owned_head_is_free() {
 let mut e=fixture();e.brains=15;begin(&mut e,PRODUCT);confirm(&mut e,true);assert_eq!(e.brains,0);
 let mut e=fixture();e.flags|=1;e.brains=0;assert!(begin(&mut e,PRODUCT));assert_eq!(e.last_alert,nil);
 assert_eq!(e.transactions,0);assert_eq!(e.selections,["skeletonHeadMaleSelected:"]);
}
#[test] fn tablet_last_product_and_duplicate_purchase_requests_use_one_dialog() {
 let mut e=fixture();begin(&mut e,"com.playforge.ZombieFarm.FarmerHead9_iPad");let alert=e.last_alert;
 begin(&mut e,PRODUCT);assert_eq!(e.last_alert,alert);confirm(&mut e,true);
 assert_eq!(e.flags,0x4100);assert_eq!(e.selections,["pumpkinHeadMaleSelected:"]);
}
#[test] fn changed_save_or_already_unlocked_during_dialog_never_double_charges() {
 let mut e=fixture();begin(&mut e,PRODUCT);e.active_data=id(8);confirm(&mut e,true);assert_eq!(e.transactions,0);
 let mut e=fixture();begin(&mut e,PRODUCT);e.flags|=1;confirm(&mut e,true);assert_eq!(e.transactions,0);
}
#[test] fn destroyed_dialog_releases_retains_and_preserves_original_dealloc_arguments() {
 let mut e=fixture();begin(&mut e,PRODUCT);e.cpu.regs=[27;16];destroyed(&mut e);
 assert_eq!(e.cpu.regs,[27;16]);assert_eq!(e.refs[&4],0);assert_eq!(e.refs[&2],0);
}
#[test] fn price_label_changes_only_locked_farmer_and_preserves_return_registers() {
 let mut e=fixture();e.cpu.regs=[31;16];label(&mut e);assert_eq!(e.label,"15脑子购买");assert_eq!(e.cpu.regs,[31;16]);
 e.available=true;e.label="选择".into();label(&mut e);assert_eq!(e.label,"选择");
}
#[test] fn unrelated_products_apps_and_menus_keep_original_behavior() {
 let mut e=fixture();assert!(!begin(&mut e,"other.product"));
 e.menu_class="OtherMenu";assert!(!begin(&mut e,PRODUCT));
 e.bundle.identifier="com.playforge.ZombieFarm2";assert!(!begin(&mut e,PRODUCT));
 assert_eq!(e.transactions,0);
}
'''


def main():
    production = SOURCE.read_text(encoding='utf-8').replace('use super::*;', '', 1).replace('//!', '//')
    # Keep tests of the real product parser, too. No substitute implementation.
    source = HARNESS.replace('// SOURCE', production)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'farmer-hook-tests.rs'
    path.write_text(source, encoding='utf-8')
    env = os.environ.copy()
    env['RUSTUP_HOME'] = str(ROOT / 'touchHLE/_build_tools/rustup')
    rustc = ROOT / 'touchHLE/_build_tools/cargo/bin/rustc.exe'
    exe = OUT / 'farmer-hook-tests.exe'
    subprocess.run([str(rustc), '--edition=2021', '--test', str(path), '-o', str(exe)], check=True, env=env)
    result = subprocess.run([str(exe), '--test-threads=1'], capture_output=True, text=True, encoding='utf-8')
    (OUT / 'farmer-hook-tests.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout, result.stderr)
    result.check_returncode()


if __name__ == '__main__':
    main()
