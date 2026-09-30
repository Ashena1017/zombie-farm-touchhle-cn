/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CGGeometry.h` (`CGPoint`, `CGSize`, `CGRect`, etc)
//!
//! See also [crate::frameworks::uikit::ui_geometry].

use std::ops::{Add, Mul, Sub};

use super::CGFloat;
use crate::abi::{impl_GuestRet_for_large_struct, GuestArg};
use crate::dyld::{export_c_func, ConstantExports, FunctionExports, HostConstant};
use crate::mem::SafeRead;
use crate::Environment;

fn parse_cg_float_list(s: &str) -> Result<Vec<CGFloat>, ()> {
    let mut values = Vec::new();
    let mut current = String::new();

    for c in s.chars() {
        let is_exponent = matches!(c, 'e' | 'E')
            && current.chars().any(|c| c.is_ascii_digit())
            && !current.contains('e')
            && !current.contains('E');
        let is_sign = matches!(c, '-' | '+')
            && (current.is_empty() || current.ends_with('e') || current.ends_with('E'));
        if c.is_ascii_digit() || c == '.' || is_exponent || is_sign {
            current.push(c);
        } else if !current.is_empty() {
            values.push(current.parse().map_err(|_| ())?);
            current.clear();
        }
    }
    if !current.is_empty() {
        values.push(current.parse().map_err(|_| ())?);
    }

    Ok(values)
}

fn parse_two_cg_floats(s: &str) -> Result<(CGFloat, CGFloat), ()> {
    let values = parse_cg_float_list(s)?;
    match values.as_slice() {
        [a, b] => Ok((*a, *b)),
        _ => Err(()),
    }
}

fn parse_four_cg_floats(s: &str) -> Result<(CGFloat, CGFloat, CGFloat, CGFloat), ()> {
    let values = parse_cg_float_list(s)?;
    match values.as_slice() {
        [a, b, c, d] => Ok((*a, *b, *c, *d)),
        _ => Err(()),
    }
}

#[derive(Copy, Clone, Debug, Default, PartialEq)]
#[repr(C, packed)]
pub struct CGPoint {
    pub x: CGFloat,
    pub y: CGFloat,
}
unsafe impl SafeRead for CGPoint {}
impl_GuestRet_for_large_struct!(CGPoint);
impl GuestArg for CGPoint {
    const REG_COUNT: usize = 2;

    fn from_regs(regs: &[u32]) -> Self {
        CGPoint {
            x: GuestArg::from_regs(&regs[0..1]),
            y: GuestArg::from_regs(&regs[1..2]),
        }
    }
    fn to_regs(self, regs: &mut [u32]) {
        self.x.to_regs(&mut regs[0..1]);
        self.y.to_regs(&mut regs[1..2]);
    }
}
impl std::str::FromStr for CGPoint {
    type Err = ();
    fn from_str(s: &str) -> Result<CGPoint, ()> {
        let (x, y) = parse_two_cg_floats(s)?;
        Ok(CGPoint { x, y })
    }
}
impl std::fmt::Display for CGPoint {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
        let &CGPoint { x, y } = self;
        write!(f, "{{{x}, {y}}}")
    }
}
// Implemented to aid animation code.
// Theres are the operations needed for the interpolation.
impl Mul<f32> for CGPoint {
    type Output = CGPoint;

    fn mul(self, rhs: f32) -> Self::Output {
        CGPoint {
            x: self.x * rhs,
            y: self.y * rhs,
        }
    }
}
impl Add<CGPoint> for CGPoint {
    type Output = CGPoint;

    fn add(self, rhs: CGPoint) -> Self::Output {
        CGPoint {
            x: self.x + rhs.x,
            y: self.y + rhs.y,
        }
    }
}
impl Sub<CGPoint> for CGPoint {
    type Output = CGPoint;

    fn sub(self, rhs: CGPoint) -> Self::Output {
        CGPoint {
            x: self.x - rhs.x,
            y: self.y - rhs.y,
        }
    }
}
// This function is rare because it is usually inlined.
fn CGPointEqualToPoint(_env: &mut Environment, a: CGPoint, b: CGPoint) -> bool {
    a == b
}

pub const CGPointZero: CGPoint = CGPoint { x: 0.0, y: 0.0 };

#[derive(Copy, Clone, Debug, Default, PartialEq)]
#[repr(C, packed)]
pub struct CGSize {
    pub width: CGFloat,
    pub height: CGFloat,
}
unsafe impl SafeRead for CGSize {}
impl_GuestRet_for_large_struct!(CGSize);
impl GuestArg for CGSize {
    const REG_COUNT: usize = 2;

    fn from_regs(regs: &[u32]) -> Self {
        CGSize {
            width: GuestArg::from_regs(&regs[0..1]),
            height: GuestArg::from_regs(&regs[1..2]),
        }
    }
    fn to_regs(self, regs: &mut [u32]) {
        self.width.to_regs(&mut regs[0..1]);
        self.height.to_regs(&mut regs[1..2]);
    }
}
impl std::str::FromStr for CGSize {
    type Err = ();
    fn from_str(s: &str) -> Result<CGSize, ()> {
        let (w, h) = parse_two_cg_floats(s)?;
        Ok(CGSize {
            width: w,
            height: h,
        })
    }
}
impl std::fmt::Display for CGSize {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
        let &CGSize { width, height } = self;
        write!(f, "{{{width}, {height}}}")
    }
}
// Implemented to aid animation code.
// Theres are the operations needed for the interpolation.
impl Mul<f32> for CGSize {
    type Output = CGSize;

    fn mul(self, rhs: f32) -> Self::Output {
        CGSize {
            width: self.width * rhs,
            height: self.height * rhs,
        }
    }
}
impl Add<CGSize> for CGSize {
    type Output = CGSize;

    fn add(self, rhs: CGSize) -> Self::Output {
        CGSize {
            width: self.width + rhs.width,
            height: self.height + rhs.height,
        }
    }
}
impl Sub<CGSize> for CGSize {
    type Output = CGSize;

    fn sub(self, rhs: CGSize) -> Self::Output {
        CGSize {
            width: self.width - rhs.width,
            height: self.height - rhs.height,
        }
    }
}
// This function is rare because it is usually inlined.
fn CGSizeEqualToSize(_env: &mut Environment, a: CGSize, b: CGSize) -> bool {
    a == b
}

pub const CGSizeZero: CGSize = CGSize {
    width: 0.0,
    height: 0.0,
};

#[derive(Copy, Clone, Debug, Default, PartialEq)]
#[repr(C, packed)]
pub struct CGRect {
    pub origin: CGPoint,
    pub size: CGSize,
}
unsafe impl SafeRead for CGRect {}
impl_GuestRet_for_large_struct!(CGRect);
impl GuestArg for CGRect {
    const REG_COUNT: usize = 4;

    fn from_regs(regs: &[u32]) -> Self {
        CGRect {
            origin: GuestArg::from_regs(&regs[0..2]),
            size: GuestArg::from_regs(&regs[2..4]),
        }
    }
    fn to_regs(self, regs: &mut [u32]) {
        self.origin.to_regs(&mut regs[0..2]);
        self.size.to_regs(&mut regs[2..4]);
    }
}
impl std::str::FromStr for CGRect {
    type Err = ();
    fn from_str(s: &str) -> Result<CGRect, ()> {
        let (x, y, width, height) = parse_four_cg_floats(s)?;
        Ok(CGRect {
            origin: CGPoint { x, y },
            size: CGSize { width, height },
        })
    }
}
impl std::fmt::Display for CGRect {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
        let &CGRect { origin, size } = self;
        write!(f, "{{{origin}, {size}}}")
    }
}
// Implemented to aid animation code.
// Theres are the operations needed for the interpolation.
impl Mul<f32> for CGRect {
    type Output = CGRect;

    fn mul(self, rhs: f32) -> Self::Output {
        CGRect {
            origin: self.origin * rhs,
            size: self.size * rhs,
        }
    }
}
impl Add<CGRect> for CGRect {
    type Output = CGRect;

    fn add(self, rhs: CGRect) -> Self::Output {
        CGRect {
            origin: self.origin + rhs.origin,
            size: self.size + rhs.size,
        }
    }
}
impl Sub<CGRect> for CGRect {
    type Output = CGRect;

    fn sub(self, rhs: CGRect) -> Self::Output {
        CGRect {
            origin: self.origin - rhs.origin,
            size: self.size - rhs.size,
        }
    }
}
// This function is rare because it is usually inlined.
fn CGRectEqualToRect(_env: &mut Environment, a: CGRect, b: CGRect) -> bool {
    a == b
}

pub const CGRectZero: CGRect = CGRect {
    origin: CGPointZero,
    size: CGSizeZero,
};

fn CGRectContainsPoint(_env: &mut Environment, rect: CGRect, point: CGPoint) -> bool {
    rect.origin.x <= point.x
        && rect.origin.x + rect.size.width > point.x
        && rect.origin.y <= point.y
        && rect.origin.y + rect.size.height > point.y
}

fn CGRectIntersectsRect(_env: &mut Environment, rect1: CGRect, rect2: CGRect) -> bool {
    rect1.origin.x.max(rect2.origin.x)
        <= (rect1.origin.x + rect1.size.width).min(rect2.origin.x + rect2.size.width)
        && rect1.origin.y.max(rect2.origin.y)
            <= (rect1.origin.y + rect1.size.height).min(rect2.origin.y + rect2.size.height)
}

fn CGRectGetMinX(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.x
}

fn CGRectGetMidX(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.x + rect.size.width / 2.0
}

fn CGRectGetMaxX(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.x + rect.size.width
}

fn CGRectGetMinY(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.y
}

fn CGRectGetMidY(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.y + rect.size.height / 2.0
}

fn CGRectGetMaxY(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.origin.y + rect.size.height
}

fn CGRectGetHeight(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.size.height
}

fn CGRectGetWidth(_env: &mut Environment, rect: CGRect) -> CGFloat {
    rect.size.width
}

fn CGRectMake(
    _env: &mut Environment,
    x: CGFloat,
    y: CGFloat,
    width: CGFloat,
    height: CGFloat,
) -> CGRect {
    CGRect {
        origin: CGPoint { x, y },
        size: CGSize { width, height },
    }
}

pub const CGRectNull: CGRect = CGRect {
    origin: CGPoint {
        x: f32::INFINITY,
        y: f32::INFINITY,
    },
    size: CGSizeZero,
};

fn CGRectIsNull(_env: &mut Environment, rect: CGRect) -> bool {
    rect == CGRectNull
}

fn CGRectIsEmpty(_env: &mut Environment, rect: CGRect) -> bool {
    rect == CGRectNull || rect.size.width <= 0.0 || rect.size.height <= 0.0
}

fn CGRectOffset(_env: &mut Environment, rect: CGRect, dx: CGFloat, dy: CGFloat) -> CGRect {
    assert!(rect != CGRectNull); // TODO
    CGRect {
        origin: CGPoint {
            x: rect.origin.x + dx,
            y: rect.origin.y + dy,
        },
        size: rect.size,
    }
}

fn CGRectInset(_env: &mut Environment, rect: CGRect, dx: CGFloat, dy: CGFloat) -> CGRect {
    let res = CGRect {
        origin: CGPoint {
            x: rect.origin.x + dx,
            y: rect.origin.y + dy,
        },
        size: CGSize {
            width: rect.size.width - 2.0 * dx,
            height: rect.size.height - 2.0 * dy,
        },
    };
    assert!(res.size.width >= 0.0); // TODO return a null rectangle
    assert!(res.size.height >= 0.0); // TODO return a null rectangle

    // center invariant
    assert!(rect.origin.x + rect.size.width / 2.0 == res.origin.x + res.size.width / 2.0);
    assert!(rect.origin.y + rect.size.height / 2.0 == res.origin.y + res.size.height / 2.0);
    res
}

#[cfg(test)]
mod tests {
    use super::{CGPoint, CGRect, CGSize};

    #[test]
    fn parses_cg_point_with_or_without_spaces() {
        assert_eq!(
            "{-33, -0}".parse::<CGPoint>(),
            Ok(CGPoint { x: -33.0, y: -0.0 })
        );
        assert_eq!(
            "{-33,-0}".parse::<CGPoint>(),
            Ok(CGPoint { x: -33.0, y: -0.0 })
        );
    }

    #[test]
    fn parses_cg_size_with_or_without_spaces() {
        assert_eq!(
            "{100, 138}".parse::<CGSize>(),
            Ok(CGSize {
                width: 100.0,
                height: 138.0,
            })
        );
        assert_eq!(
            "{100,138}".parse::<CGSize>(),
            Ok(CGSize {
                width: 100.0,
                height: 138.0,
            })
        );
    }

    #[test]
    fn parses_cg_rect_with_or_without_spaces() {
        let rect = CGRect {
            origin: CGPoint { x: 62.0, y: 98.0 },
            size: CGSize {
                width: 34.0,
                height: 24.0,
            },
        };
        assert_eq!("{{62, 98}, {34, 24}}".parse::<CGRect>(), Ok(rect));
        assert_eq!("{{62,98},{34,24}}".parse::<CGRect>(), Ok(rect));
    }
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CGPointEqualToPoint(_, _)),
    export_c_func!(CGSizeEqualToSize(_, _)),
    export_c_func!(CGRectEqualToRect(_, _)),
    export_c_func!(CGRectContainsPoint(_, _)),
    export_c_func!(CGRectIntersectsRect(_, _)),
    export_c_func!(CGRectGetMinX(_)),
    export_c_func!(CGRectGetMidX(_)),
    export_c_func!(CGRectGetMaxX(_)),
    export_c_func!(CGRectGetMinY(_)),
    export_c_func!(CGRectGetMidY(_)),
    export_c_func!(CGRectGetMaxY(_)),
    export_c_func!(CGRectGetHeight(_)),
    export_c_func!(CGRectGetWidth(_)),
    export_c_func!(CGRectMake(_, _, _, _)),
    export_c_func!(CGRectIsNull(_)),
    export_c_func!(CGRectIsEmpty(_)),
    export_c_func!(CGRectOffset(_, _, _)),
    export_c_func!(CGRectInset(_, _, _)),
];

pub const CONSTANTS: ConstantExports = &[
    (
        "_CGSizeZero",
        HostConstant::Custom(|env| env.mem.alloc_and_write(CGSizeZero).cast().cast_const()),
    ),
    (
        "_CGPointZero",
        HostConstant::Custom(|env| env.mem.alloc_and_write(CGPointZero).cast().cast_const()),
    ),
    (
        "_CGRectZero",
        HostConstant::Custom(|env| env.mem.alloc_and_write(CGRectZero).cast().cast_const()),
    ),
    (
        "_CGRectNull",
        HostConstant::Custom(|env| env.mem.alloc_and_write(CGRectNull).cast().cast_const()),
    ),
];
