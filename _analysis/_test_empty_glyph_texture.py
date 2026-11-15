"""Exercise the production empty-glyph hook's guest ABI and buffer ownership."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_analysis/dumps/android-shop-black-20261115'


def main():
    source = (ROOT / 'touchHLE/touchHLE-fork/src/objc/messages/zombie_farm.rs').read_text(encoding='utf-8')
    start = source.index('fn zombie_farm_normalize_empty_text_texture(')
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    production = source[start:end]
    harness = r'''
#![allow(non_camel_case_types, dead_code)]
use std::{marker::PhantomData, ops::Add, sync::atomic::{AtomicBool, Ordering}};
macro_rules! log { ($($args:tt)*) => {{ let _ = format!($($args)*); }} }
#[derive(Copy, Clone, Debug, PartialEq)] struct id(u32);
impl id { fn to_bits(self)->u32 {self.0} }
type SEL=u32;
#[repr(C)] #[derive(Copy, Clone, Debug, PartialEq)] struct CGSize {width:f32,height:f32}
#[derive(Copy, Clone)] struct ConstPtr<T:Copy=()> {addr:u32,marker:PhantomData<T>}
impl<T:Copy> ConstPtr<T> {
 fn from_bits(addr:u32)->Self {Self {addr,marker:PhantomData}}
 fn cast<U:Copy>(self)->ConstPtr<U> {ConstPtr::from_bits(self.addr)}
 fn cast_const(self)->Self {self}
}
impl<T:Copy> Add<u32> for ConstPtr<T> {type Output=Self;fn add(self,n:u32)->Self {Self::from_bits(self.addr+n*std::mem::size_of::<T>() as u32)}}
struct Cpu {r:[u32;16]}
impl Cpu { const SP:usize=13;fn regs(&self)->&[u32;16] {&self.r} fn regs_mut(&mut self)->&mut[u32;16] {&mut self.r} }
struct Mem {bytes:Vec<u8>,live:Vec<u32>,freed:Vec<u32>,next:u32}
impl Mem {
 fn read<T:Copy>(&self,p:ConstPtr<T>)->T {unsafe{self.bytes.as_ptr().add(p.addr as usize).cast::<T>().read_unaligned()}}
 fn write<T:Copy>(&mut self,p:ConstPtr<T>,v:T) {unsafe{self.bytes.as_mut_ptr().add(p.addr as usize).cast::<T>().write_unaligned(v)}}
 fn alloc(&mut self,n:u32)->ConstPtr<()> {assert_eq!(n,1);let addr=self.next;self.next+=16;self.live.push(addr);self.bytes[addr as usize]=0xcc;ConstPtr::from_bits(addr)}
 fn free(&mut self,p:ConstPtr<()>) {let i=self.live.iter().position(|&a|a==p.addr).expect("free must own scratch pixel");self.live.remove(i);self.freed.push(p.addr);}
}
struct Bundle {identifier:&'static str,version:&'static str}
impl Bundle {fn bundle_identifier(&self)->&str {self.identifier} fn bundle_version(&self)->&str {self.version}}
struct Environment {cpu:Cpu,mem:Mem,bundle:Bundle,class:&'static str,calls:usize,observed:Option<(u32,u32,u32,CGSize)>}
fn zombie_farm_object_class_name(e:&Environment,_:id)->Option<&str> {Some(e.class)}
const SELECTOR:&str="initWithData:pixelFormat:pixelsWide:pixelsHigh:contentSize:";
fn msg_send_no_type_checking(e:&mut Environment,args:(id,SEL,ConstPtr<()>,u32,u32,u32,CGSize))->id {
 assert_eq!(args.3,3);assert_eq!((args.4,args.5),(1,1));assert_eq!((args.6.width,args.6.height),(0.0,0.0));
 assert_ne!(args.2.addr,0x200);assert_eq!(e.mem.read(args.2.cast::<u8>()),0);
 let original_stack=e.mem.bytes[0x100..0x110].to_vec();
 e.mem.write(ConstPtr::from_bits(0x100),1u32);e.mem.write(ConstPtr::from_bits(0x104),1u32);
 assert!(!zombie_farm_normalize_empty_text_texture(e,args.0,args.1,SELECTOR),"recursive dispatch must reach the original guest method");
 e.mem.bytes[0x100..0x110].copy_from_slice(&original_stack);
 e.calls+=1;e.observed=Some((args.2.addr,args.4,args.5,args.6));id(0x1234)
}
// PRODUCTION
fn fixture()->Environment {
 let mut e=Environment {cpu:Cpu {r:[0;16]},mem:Mem {bytes:vec![0;4096],live:vec![],freed:vec![],next:0x300},
  bundle:Bundle {identifier:"com.playforge.ZombieFarm.ZFR",version:"1.0"},class:"CCTexture2D",calls:0,observed:None};
 e.cpu.r[3]=3;e.cpu.r[2]=0x200;e.cpu.r[Cpu::SP]=0x100;e.mem.bytes[0x200]=0x5a;e
}
fn invoke(e:&mut Environment)->bool {zombie_farm_normalize_empty_text_texture(e,id(0x80),7,SELECTOR)}
fn unchanged(mut e:Environment) {
 let bytes=e.mem.bytes.clone();let regs=e.cpu.r;
 assert!(!invoke(&mut e));assert_eq!(e.mem.bytes,bytes);assert_eq!(e.cpu.r,regs);assert_eq!(e.calls,0);assert!(e.mem.freed.is_empty());
}
#[test] fn empty_glyph_has_finite_metadata_and_zero_layout_without_freeing_caller_data() {
 let mut e=fixture();let stack=e.mem.bytes[0x100..0x110].to_vec();assert!(invoke(&mut e));
 assert_eq!(e.calls,1);assert!(e.mem.live.is_empty());assert_eq!(e.mem.freed.len(),1);assert_eq!(e.cpu.r[0],0x1234);
 assert_eq!(e.mem.bytes[0x200],0x5a);assert_eq!(e.mem.bytes[0x100..0x110],stack);
 let (_,w,h,size)=e.observed.unwrap();assert!((size.width/w as f32).is_finite());assert!((size.height/h as f32).is_finite());
}
#[test] fn ordinary_text_and_image_formats_are_unchanged() {
 let mut e=fixture();e.mem.write(ConstPtr::from_bits(0x100),128u32);e.mem.write(ConstPtr::from_bits(0x104),64u32);unchanged(e);
 for format in [0,1,2,4,5,6] {let mut e=fixture();e.cpu.r[3]=format;unchanged(e);}
}
#[test] fn partial_zero_sizes_and_nonzero_or_nan_content_are_unchanged() {
 for (w,h,cw,ch) in [(0,8,0.0,0.0),(8,0,0.0,0.0),(0,0,1.0,0.0),(0,0,0.0,1.0),(0,0,f32::NAN,0.0)] {
  let mut e=fixture();e.mem.write(ConstPtr::from_bits(0x100),w as u32);e.mem.write(ConstPtr::from_bits(0x104),h as u32);
  e.mem.write(ConstPtr::from_bits(0x108),CGSize {width:cw,height:ch});unchanged(e);
 }
}
#[test] fn other_classes_apps_versions_and_selectors_are_unchanged() {
 let mut e=fixture();e.class="OtherTexture";unchanged(e);
 let mut e=fixture();e.bundle.identifier="com.playforge.ZombieFarm2";unchanged(e);
 let mut e=fixture();e.bundle.version="2.0";unchanged(e);
 let mut e=fixture();assert!(!zombie_farm_normalize_empty_text_texture(&mut e,id(0x80),7,"otherSelector"));assert_eq!(e.calls,0);
}
'''.replace('// PRODUCTION', production)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'empty-glyph-tests.rs'
    path.write_text(harness, encoding='utf-8')
    env = os.environ.copy()
    env['RUSTUP_HOME'] = str(ROOT / 'touchHLE/_build_tools/rustup')
    subprocess.run([str(ROOT/'touchHLE/_build_tools/cargo/bin/rustc.exe'), '--edition=2021', '--test', str(path),
                    '-o', str(OUT/'empty-glyph-tests.exe')], check=True, env=env)
    result = subprocess.run([str(OUT/'empty-glyph-tests.exe'), '--test-threads=1'], check=True, capture_output=True, text=True)
    print(result.stdout)
    (OUT/'empty-glyph-tests.txt').write_text(result.stdout, encoding='utf-8')


if __name__ == '__main__':
    main()
