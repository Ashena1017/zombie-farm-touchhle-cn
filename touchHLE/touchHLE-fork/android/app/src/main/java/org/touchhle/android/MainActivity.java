/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Parts of this file are derived from SDL 2's Android project template, which
 * has a different license. Please see vendor/SDL/LICENSE.txt for details.
 */
package org.touchhle.android;

import android.os.Build;
import android.os.Bundle;
import android.content.Intent;
import android.app.AlertDialog;
import android.widget.Toast;
import org.json.JSONObject;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

import org.libsdl.app.SDLActivity;

/**
 * A wrapper class over SDLActivity
 */

public class MainActivity extends SDLActivity {
    private ZfStorage.Lease gameLease;
    private String[] launchArguments = new String[0];

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        try {
            ZfStorage storage = new ZfStorage(this);
            gameLease = storage.lock();
            storage.ensureBundled();
            ZfIpa ipa = storage.selected();
            JSONObject settings = storage.settings(ipa.appId);
            android.system.Os.setenv("TOUCHHLE_TIME_OFFSET_SECONDS",
                Long.toString(settings.optLong("offset", 0)), true);
            android.system.Os.setenv("TOUCHHLE_ANDROID_RUN_LOOP_FIX",
                settings.optBoolean("fix", true) ? "1" : "0", true);
            launchArguments = new String[]{ipa.file.getPath(), "--landscape-right",
                "--device-family=" + settings.optString("family", "iphone"),
                "--scale-hack=" + settings.optString("scale", "1"),
                "--fps-limit=" + settings.optString("fps", "60")};
        } catch (Exception e) {
            Toast.makeText(this, "无法启动：" + e.getMessage(), Toast.LENGTH_LONG).show();
            super.onCreate(savedInstanceState);
            finish();
            return;
        }
        super.onCreate(savedInstanceState);
        hideSystemBars();
    }

    @Override
    protected String[] getArguments() { return launchArguments; }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent.getBooleanExtra("stop_game", false)) finish();
    }

    @Override
    public void onBackPressed() {
        new AlertDialog.Builder(this).setTitle("返回游戏管理？")
            .setNegativeButton("继续游戏", null)
            .setPositiveButton("退出游戏", (dialog, which) -> finish()).show();
    }

    @Override
    protected void onDestroy() {
        try {
            super.onDestroy();
        } finally {
            if (gameLease != null) {
                try { gameLease.close(); } catch (java.io.IOException ignored) {}
            }
            // Reset SDL, the emulator and its cached clock for the next launch.
            // Only this dedicated :game process exits; the manager stays alive.
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemBars();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemBars();
        }
    }

    @Override
    public void onSystemUiVisibilityChange(int visibility) {
        // SDL can request a windowed style while creating or rotating its window.
        // Keep this Android game fullscreen, including after those requests.
        if (!mFullscreenModeActive && hasWindowFocus()) {
            hideSystemBars();
        }
        super.onSystemUiVisibilityChange(visibility);
    }

    private void hideSystemBars() {
        Window window = getWindow();
        window.clearFlags(WindowManager.LayoutParams.FLAG_FORCE_NOT_FULLSCREEN);
        window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        mFullscreenModeActive = true;

        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false);
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                controller.setSystemBarsBehavior(
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controller.hide(WindowInsets.Type.systemBars());
            }
        } else {
            window.getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    @Override
    protected String[] getLibraries() {
        return new String[]{
            "SDL2",
            "touchHLE"
        };
    }
}
