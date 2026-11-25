/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.content.SharedPreferences;
import android.graphics.Color;

/** Manager preferences belong to the launcher, independently of the active game. */
final class ZfAppearance {
    static final String LIGHT = "light", DARK = "dark", SYSTEM = "system";
    static final String[] NAMES = {"豆沙粉", "珊瑚红", "琥珀橙", "青绿", "湖蓝", "丁香紫", "石墨灰"};
    static final int[] COLORS = {0xffb57b98, 0xffcb705d, 0xffb57732, 0xff469782, 0xff568eb5, 0xff7957a7, 0xff75818d};
    static final int CUSTOM = -1;

    private final SharedPreferences prefs;
    String mode;
    int choice, custom;

    ZfAppearance(SharedPreferences prefs) {
        this.prefs = prefs;
        mode = prefs.getString("appearance_mode", SYSTEM);
        if (!prefs.contains("appearance_mode") && prefs.contains("night_mode"))
            mode = prefs.getBoolean("night_mode", true) ? DARK : LIGHT;
        choice = prefs.getInt("appearance_accent", 0);
        if (choice < CUSTOM || choice >= COLORS.length) choice = 0;
        custom = prefs.getInt("appearance_custom", COLORS[0]) | 0xff000000;
    }

    boolean dark(boolean systemDark) {
        return DARK.equals(mode) || (!LIGHT.equals(mode) && systemDark);
    }

    int accent() { return choice == CUSTOM ? custom : COLORS[choice]; }

    void save() {
        prefs.edit().remove("night_mode").putString("appearance_mode", mode)
            .putInt("appearance_accent", choice).putInt("appearance_custom", custom).apply();
    }

    void reset() {
        mode = SYSTEM;
        choice = 0;
        custom = COLORS[0];
        save();
    }

    static int mix(int start, int end, double amount) {
        double keep = 1 - amount;
        return Color.rgb((int)Math.round(keep * Color.red(start) + amount * Color.red(end)),
            (int)Math.round(keep * Color.green(start) + amount * Color.green(end)),
            (int)Math.round(keep * Color.blue(start) + amount * Color.blue(end)));
    }

    private static double linear(int value) {
        double s = value / 255.0;
        return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    }

    private static double luminance(int color) {
        return 0.2126 * linear(Color.red(color)) + 0.7152 * linear(Color.green(color)) + 0.0722 * linear(Color.blue(color));
    }

    static double contrast(int a, int b) {
        double x = luminance(a), y = luminance(b);
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    }

    static int foreground(int background) {
        return contrast(Color.BLACK, background) > contrast(Color.WHITE, background) ? Color.BLACK : Color.WHITE;
    }

    static int readableAccent(int color, int background) {
        int target = foreground(background), adjusted = color;
        for (int step = 1; contrast(adjusted, background) < 4.5; step++)
            adjusted = mix(color, target, step / 20.0);
        return adjusted;
    }

    static final class Palette {
        final boolean dark;
        final int accent, onAccent, accentText, ink, muted, background, surface, soft, line;

        Palette(int accent, boolean dark) {
            this.dark = dark;
            this.accent = accent;
            onAccent = foreground(accent);
            background = mix(dark ? 0xff1d1d20 : 0xfffaf9fa, accent, dark ? 0.05 : 0.04);
            surface = mix(dark ? 0xff272629 : Color.WHITE, accent, dark ? 0.05 : 0.01);
            soft = mix(surface, accent, dark ? 0.17 : 0.12);
            line = mix(dark ? 0xff49454a : 0xffdedade, accent, 0.20);
            ink = dark ? 0xfff7f3f6 : 0xff272328;
            muted = dark ? 0xffc8c0c5 : 0xff625a60;
            int leastContrasting = background;
            int neutralText = dark ? Color.WHITE : Color.BLACK;
            for (int base : new int[]{surface, soft}) {
                if (contrast(neutralText, base) < contrast(neutralText, leastContrasting)) leastContrasting = base;
            }
            accentText = readableAccent(accent, leastContrasting);
        }
    }
}
