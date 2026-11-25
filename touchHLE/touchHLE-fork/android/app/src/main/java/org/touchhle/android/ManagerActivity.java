/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.app.*;
import android.content.*;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

/** Native touch-first launcher; the emulator runs in the separate :game process. */
public class ManagerActivity extends Activity {
    private static final int IMPORT_IPA = 10, IMPORT_SAVE = 11, EXPORT_SAVE = 12;
    private static final String[] SCALE_PRESETS = {"1", "1.25", "1.5", "1.75", "2", "3", "4", "5", "6"};

    // Free / open-source statement.
    //
    // Copies of this app turn up for sale. The only thing that helps the person
    // who paid is telling them, from inside the app, that it is a free download
    // and where the original lives. Shown on EVERY launch -- a seller who opens
    // the app once before handing the phone over must not be able to make the
    // statement disappear for the buyer -- and kept on screen as the footer line.
    private static final String PROJECT_URL = "https://github.com/Ashena1017/zombie-farm-touchhle-cn";
    private static final String QQ_GROUP = "1185712984";
    private static final String NOTICE_VERSION = "2";
    // SHA-256 of the signing certificate this project is built with. A repack
    // signed with someone else's key will not match, which is exactly the case
    // worth warning about: re-signed copies are how ads or a paywall get bolted
    // on before resale. Update this constant if the keystore ever changes.
    static final String OFFICIAL_CERT =
        "c2ddca91eb8e54a081b768450f8a154d49219427674377a24ae9561f3814ca6f";

    private ZfAppearance appearance;
    private ZfAppearance.Palette palette;
    private boolean appearanceOpen;
    private ZfAppearanceView appearanceView;
    private AlertDialog noticeDialog;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private ZfStorage storage;
    private List<ZfIpa> versions = new ArrayList<>();
    private List<File> backups = new ArrayList<>();
    private ZfIpa selected;
    private String bundledWarning;
    private JSONObject settings = new JSONObject();
    private ZfSave currency;
    private String saveMessage = "还没有存档，请先进入游戏";
    private boolean busy, running;
    private int page;
    private LinearLayout shell, body;
    private Spinner family, scale, fps;
    private EditText customScale, customFps;
    private Switch fix;
    private TextView resolution;
    private String pendingId;
    private File exportFile;
    private final Handler statusHandler = new Handler(Looper.getMainLooper());
    private final Handler settingsHandler = new Handler(Looper.getMainLooper());
    private final Runnable settingsSaveRequest = this::flushSettingsSave;
    private JSONObject pendingSettings;
    private String pendingSettingsId;
    private JSONObject submittedSettings;
    private TextView settingsStatus;
    private TextView simulatedClock;
    private Runnable skipPreview;
    private final Runnable statusCheck = new Runnable() {
        @Override public void run() {
            if (simulatedClock != null) updateSimulatedClock();
            if (skipPreview != null) skipPreview.run();
            // Resume can precede the game process releasing its lease on exit.
            if (storage != null && !busy && running != storage.gameRunning()) refresh(false);
            statusHandler.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (Build.VERSION.SDK_INT >= 26) {
            PackageInfo webview = android.webkit.WebView.getCurrentWebViewPackage();
            if (webview != null && android.text.TextUtils.isDigitsOnly(webview.versionName.split("\\.")[0])
                    && Integer.parseInt(webview.versionName.split("\\.")[0]) >= 105) {
                startActivity(new Intent(this, MobileManagerActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
                finish();
                return;
            }
        }
        if (state != null) {
            appearanceOpen = state.getBoolean("appearance_open");
            page = state.getInt("page", 0); pendingId = state.getString("pendingId");
            String path = state.getString("exportFile"); if (path != null) exportFile = new File(path);
        }
        appearance = new ZfAppearance(getPreferences(MODE_PRIVATE));
        applyPalette();
        try { storage = new ZfStorage(this); }
        catch (Exception e) { error(e); return; }
        setTitle("Zombie Farm 游戏管理"); render();
        verifySignature();
        if (state == null || state.getBoolean("notice_open")) showNoticeIfNeeded();
    }
    @Override protected void onResume() {
        super.onResume(); if (storage != null && !busy) refresh(true);
        statusHandler.removeCallbacks(statusCheck); statusHandler.postDelayed(statusCheck, 1000);
    }
    @Override protected void onPause() {
        statusHandler.removeCallbacks(statusCheck);
        flushSettingsSave();
        super.onPause();
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putBoolean("appearance_open", appearanceOpen);
        state.putBoolean("notice_open", noticeDialog != null && noticeDialog.isShowing());
        state.putInt("page", page); state.putString("pendingId", pendingId);
        if (exportFile != null) state.putString("exportFile", exportFile.getPath());
        super.onSaveInstanceState(state);
    }
    @Override protected void onDestroy() {
        statusHandler.removeCallbacks(statusCheck);
        settingsHandler.removeCallbacksAndMessages(null);
        worker.shutdown(); super.onDestroy();
    }

    private void applyPalette() {
        boolean systemDark = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        palette = new ZfAppearance.Palette(appearance.accent(), appearance.dark(systemDark));
        getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(palette.background));
        // White system icons work on every supported API, including Android 5.
        getWindow().setStatusBarColor(ZfAppearance.mix(palette.accent, Color.BLACK, 0.58));
        getWindow().setNavigationBarColor(ZfAppearance.mix(palette.accent, Color.BLACK, 0.83));
    }

    private AlertDialog.Builder dialogBuilder() {
        return new AlertDialog.Builder(this, palette.dark
            ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert) {
            @Override public AlertDialog show() {
                AlertDialog dialog = super.show();
                tintDialogButtons(dialog);
                return dialog;
            }
        };
    }

    void tintDialogButtons(AlertDialog dialog) {
        ColorStateList text = new ColorStateList(new int[][]{new int[]{android.R.attr.state_enabled}, new int[]{}},
            new int[]{palette.accentText, (palette.muted & 0x00ffffff) | 0x77000000});
        for (int which : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEGATIVE, AlertDialog.BUTTON_NEUTRAL}) {
            Button button = dialog.getButton(which);
            if (button != null) button.setTextColor(text);
        }
    }

    private interface Task { String run() throws Exception; }
    private void task(Task action) { task(action, null); }
    private void task(Task action, Runnable after) {
        if (busy) return;
        flushSettingsSave();
        busy = true; render();
        worker.execute(() -> {
            String message = null; Exception failure = null;
            try (ZfStorage.Lease ignored = storage.lock()) { message = action.run(); }
            catch (Exception e) { failure = e; }
            final String result = message; final Exception problem = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                busy = false;
                if (problem != null) error(problem); else if (result != null) toast(result);
                if (problem == null && after != null) after.run();
                refresh(false);
            });
        });
    }
    private void refresh(boolean install) {
        if (busy) return;
        flushSettingsSave();
        busy = true; render();
        worker.execute(() -> {
            Exception failure = null;
            String warning = bundledWarning;
            try {
                if (install && !storage.gameRunning()) {
                    try (ZfStorage.Lease ignored = storage.lock()) { warning = storage.ensureBundled(); }
                }
                versions = storage.versions();
                selected = storage.selectedFrom(versions);
                running = storage.gameRunning(); currency = null;
                if (selected != null) {
                    settings = storage.settings(selected.appId);
                    if (!running) {
                        try { currency = storage.currency(selected.appId); saveMessage = "当前存档已校验"; }
                        catch (Exception e) { saveMessage = storage.live(selected.appId).exists() ? e.getMessage() : "还没有存档，请先进入游戏"; }
                    } else saveMessage = "游戏运行中，退出后可管理存档";
                    backups = storage.backups(selected.appId);
                }
            } catch (Exception e) { failure = e; }
            final Exception problem = failure;
            final String checkedWarning = warning;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                boolean notify = checkedWarning != null && !checkedWarning.equals(bundledWarning);
                bundledWarning = checkedWarning;
                busy = false; render(); if (problem != null) error(problem);
                if (notify) showBundledWarning(this, checkedWarning);
            });
        });
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setPadding(0, dp(4), 0, dp(4)); return view;
    }
    private LinearLayout vertical() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private LinearLayout row() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.HORIZONTAL); v.setGravity(Gravity.CENTER_VERTICAL); return v; }
    private GradientDrawable shape(int color, int radius) {
        GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d;
    }
    private Button button(String title, boolean primary, Runnable action) {
        Button b = new Button(this); b.setText(title); b.setAllCaps(false); b.setTextSize(15);
        b.setTextColor(primary ? palette.onAccent : palette.accentText);
        b.setBackground(shape(primary ? palette.accent : palette.soft, 6));
        b.setMinHeight(dp(48)); b.setStateListAnimator(null);
        b.setOnClickListener(v -> action.run()); return b;
    }
    private void addButton(LinearLayout parent, Button button) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(52)); p.topMargin = dp(6); parent.addView(button, p);
    }
    private void pair(LinearLayout parent, View first, View second) {
        LinearLayout r = row(); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -2, 1); p.setMargins(0, 0, dp(8), 0);
        r.addView(first, p); r.addView(second, new LinearLayout.LayoutParams(0, -2, 1)); parent.addView(r);
    }
    private LinearLayout card(String title, String subtitle) {
        LinearLayout card = vertical(); card.setPadding(dp(16), dp(13), dp(16), dp(14));
        GradientDrawable surface = shape(palette.surface, 6); surface.setStroke(dp(1), palette.line); card.setBackground(surface);
        card.addView(text(title, 17, palette.ink, true));
        if (subtitle != null) card.addView(text(subtitle, 13, palette.muted, false));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.bottomMargin = dp(10); body.addView(card, p);
        return card;
    }
    private boolean editable() { return !busy && !running && selected != null; }
    private void render() {
        flushSettingsSave();
        family = null;
        settingsStatus = null;
        simulatedClock = null;
        shell = vertical(); shell.setBackgroundColor(palette.background); shell.setPadding(dp(14), dp(12), dp(14), 0);
        if (appearanceOpen) {
            int scrollY = appearanceView == null ? 0 : appearanceView.getScrollY();
            ZfAppearanceView controls = new ZfAppearanceView(this, appearance, palette, () -> {
                applyPalette(); render();
            }, this::closeAppearance);
            appearanceView = controls;
            shell.addView(controls, new LinearLayout.LayoutParams(-1, 0, 1));
            addFooter();
            setContentView(shell);
            if (scrollY > 0) controls.post(() -> controls.scrollTo(0, scrollY));
            return;
        }
        FrameLayout hero = new FrameLayout(this); hero.setBackground(shape(palette.soft, 8)); hero.setClipToOutline(true);
        LinearLayout titles = vertical(); titles.setPadding(dp(17), dp(17), 0, 0);
        titles.addView(text("Zombie Farm 游戏管理", 20, palette.ink, true));
        titles.addView(text("僵尸农场 · 中文版 · 免费开源", 12, palette.muted, false));
        TextView state = text(busy ? "处理中…" : running ? "游戏运行中" : "准备就绪", 11, palette.accentText, true);
        state.setPadding(dp(9), dp(4), dp(9), dp(4)); state.setBackground(shape(palette.surface, 12));
        LinearLayout.LayoutParams stateParams = new LinearLayout.LayoutParams(-2, -2);
        stateParams.topMargin = dp(4); titles.addView(state, stateParams);
        FrameLayout.LayoutParams titleParams = new FrameLayout.LayoutParams(-1, -1, Gravity.TOP | Gravity.LEFT);
        hero.addView(titles, titleParams);
        View accent = new View(this); accent.setBackgroundColor(palette.accent);
        FrameLayout.LayoutParams accentParams = new FrameLayout.LayoutParams(dp(36), dp(2), Gravity.LEFT | Gravity.BOTTOM);
        accentParams.setMargins(dp(17), 0, 0, dp(13)); hero.addView(accent, accentParams);
        Button themeButton = new Button(this);
        themeButton.setText("外观"); themeButton.setTextSize(14);
        themeButton.setTextColor(palette.accentText); themeButton.setContentDescription("外观");
        themeButton.setPadding(dp(8), 0, dp(8), 0); themeButton.setMinWidth(0); themeButton.setMinimumWidth(0);
        themeButton.setMinHeight(0); themeButton.setMinimumHeight(0); themeButton.setStateListAnimator(null);
        GradientDrawable themeBg = shape(palette.surface, 8); themeBg.setStroke(dp(1), palette.line); themeButton.setBackground(themeBg);
        FrameLayout.LayoutParams themeParams = new FrameLayout.LayoutParams(dp(60), dp(48), Gravity.TOP | Gravity.RIGHT);
        themeParams.setMargins(0, dp(48), dp(10), 0); hero.addView(themeButton, themeParams);
        themeButton.setOnClickListener(v -> { appearanceOpen = true; render(); });
        LinearLayout.LayoutParams heroParams = new LinearLayout.LayoutParams(-1, dp(142)); heroParams.bottomMargin = dp(10);
        shell.addView(hero, heroParams);
        LinearLayout nav = row(); nav.setPadding(dp(4), dp(3), dp(4), dp(3));
        GradientDrawable navBg = shape(palette.surface, 7); navBg.setStroke(dp(1), palette.line); nav.setBackground(navBg);
        String[] tabs = {"游戏", "设置", "存档"};
        for (int i = 0; i < tabs.length; i++) {
            final int index = i; Button b = new Button(this); b.setText(tabs[i]); b.setAllCaps(false); b.setTextSize(14);
            b.setTextColor(page == i ? palette.onAccent : palette.muted); b.setBackground(shape(page == i ? palette.accent : Color.TRANSPARENT, 5));
            b.setMinHeight(0); b.setMinimumHeight(dp(42)); b.setPadding(dp(4), 0, dp(4), 0); b.setStateListAnimator(null);
            b.setOnClickListener(v -> { page = index; render(); }); b.setEnabled(!busy);
            LinearLayout.LayoutParams tabParams = new LinearLayout.LayoutParams(0, dp(42), 1);
            tabParams.setMargins(dp(2), 0, dp(2), 0); nav.addView(b, tabParams);
        }
        LinearLayout.LayoutParams navParams = new LinearLayout.LayoutParams(-1, -2); navParams.bottomMargin = dp(4); shell.addView(nav, navParams);
        ScrollView scroller = new ScrollView(this); scroller.setFillViewport(true);
        body = vertical(); body.setPadding(0, dp(8), 0, dp(18)); scroller.addView(body);
        shell.addView(scroller, new LinearLayout.LayoutParams(-1, 0, 1));
        addFooter();
        setContentView(shell);
        if (selected == null) {
            if (busy || bundledWarning == null) card("正在准备游戏", "首次打开会安装内置中文版，请稍候。");
            else {
                LinearLayout empty = card("没有可用的游戏版本", bundledWarning);
                addButton(empty, button("导入 IPA", false, () -> chooseFile(IMPORT_IPA)));
            }
            return;
        }
        if (page == 0) gamePage(); else if (page == 1) settingsPage(); else savePage();
    }
    @Override public void onBackPressed() {
        if (appearanceOpen) closeAppearance(); else super.onBackPressed();
    }

    private void closeAppearance() {
        appearanceOpen = false;
        appearanceView = null;
        render();
    }

    private void addFooter() {
        // The footer is outside the scroll view: it is the one line that has to
        // be visible on every page without scrolling, which is the whole point.
        TextView footer = text("免费开源 · 唯一官方来源 github.com/Ashena1017/zombie-farm-touchhle-cn\n交流群 QQ 1185712984 · 付费购买请联系退款",
            10, palette.muted, false);
        footer.setGravity(Gravity.CENTER); footer.setPadding(dp(4), dp(6), dp(4), dp(10));
        footer.setOnClickListener(v -> showProjectNotice(false));
        shell.addView(footer, new LinearLayout.LayoutParams(-1, -2));
    }

    private Spinner spinner(String[] values) {
        Spinner s = new Spinner(this); ArrayAdapter<String> adapter = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, values) {
            @Override public View getView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getView(position, convertView, parent); v.setTextColor(palette.ink); return v;
            }
            @Override public View getDropDownView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getDropDownView(position, convertView, parent);
                v.setTextColor(palette.ink); v.setBackgroundColor(palette.surface); return v;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); s.setAdapter(adapter); s.setMinimumHeight(dp(48));
        s.setBackgroundTintList(ColorStateList.valueOf(palette.line));
        s.setEnabled(editable()); return s;
    }
    private EditText number(String hint, String value, boolean decimal) {
        EditText e = new EditText(this); e.setTextSize(16); e.setSingleLine(true); e.setHint(hint); e.setText(value);
        e.setInputType(decimal ? InputType.TYPE_CLASS_TEXT : InputType.TYPE_CLASS_NUMBER);
        e.setTextColor(palette.ink); e.setHintTextColor(palette.muted); e.setBackgroundTintList(ColorStateList.valueOf(palette.line));
        e.setEnabled(editable()); return e;
    }
    private void gamePage() {
        LinearLayout version = card("游戏版本", "内置最新中文修复版，也可导入其他版本。");
        Spinner picker = new Spinner(this); ArrayAdapter<ZfIpa> adapter = new ArrayAdapter<ZfIpa>(this, android.R.layout.simple_spinner_item, versions) {
            @Override public View getView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getView(position, convertView, parent); v.setTextColor(palette.ink); return v;
            }
            @Override public View getDropDownView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getDropDownView(position, convertView, parent);
                v.setTextColor(palette.ink); v.setBackgroundColor(palette.surface); return v;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); picker.setAdapter(adapter); picker.setMinimumHeight(dp(48));
        picker.setBackgroundTintList(ColorStateList.valueOf(palette.line));
        int current = 0; for (int i = 0; i < versions.size(); i++) if (versions.get(i).file.equals(selected.file)) current = i;
        picker.setSelection(current); picker.setEnabled(editable()); version.addView(picker);
        picker.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                ZfIpa choice = versions.get(pos);
                if (!choice.file.equals(selected.file)) task(() -> { storage.select(choice); return "已切换游戏版本"; });
            }
        });
        version.addView(text("游戏版本 " + selected.version + " · " + String.format(Locale.ROOT, "%.1f MB", selected.file.length() / 1048576.0), 12, palette.muted, false));
        Button importButton = button("导入 IPA", false, () -> chooseFile(IMPORT_IPA)); importButton.setEnabled(editable()); addButton(version, importButton);
        LinearLayout launch = card("开始游戏", "累计跳过 " + duration(settings.optLong("offset", 0)));
        simulatedClock = text("", 15, palette.ink, true);
        launch.addView(simulatedClock); updateSimulatedClock();
        if (running) {
            addButton(launch, button("返回正在运行的游戏", true, () -> startActivity(new Intent(this, MainActivity.class))));
            addButton(launch, button("退出游戏并返回管理器", false, () -> startActivity(new Intent(this, MainActivity.class)
                .putExtra("stop_game", true).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP))));
        } else {
            Button start = button("启动游戏", true, () -> launch(0)); start.setEnabled(editable()); addButton(launch, start);
            Button skip = button("启动并跳过时间", false, this::skipDialog); skip.setEnabled(editable()); addButton(launch, skip);
            if (settings.optLong("offset", 0) > 0) {
                Button reset = button("重置累计跳过时间", false, () -> dialogBuilder()
                    .setTitle("重置累计时间？")
                    .setMessage("只清除未来启动时使用的累计偏移，不会倒退或改写现有游戏进度。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("重置", (dialog, which) -> {
                        String id = selected.appId;
                        task(() -> {
                            storage.settings(id, storage.settings(id).put("offset", 0));
                            return "累计跳过时间已重置";
                        });
                    }).show());
                reset.setEnabled(editable()); addButton(launch, reset);
            }
        }
        LinearLayout money = card("金币与脑子", saveMessage);
        EditText gold = number("金币", currency == null ? "" : Integer.toString(currency.gold), false);
        EditText brains = number("脑子", currency == null ? "" : Integer.toString(currency.brains), false);
        LinearLayout left = vertical(), right = vertical(); left.addView(text("金币", 13, palette.muted, false)); left.addView(gold);
        right.addView(text("脑子", 13, palette.muted, false)); right.addView(brains); pair(money, left, right);
        Button apply = button("保存货币修改", false, () -> {
            try {
                int g = Integer.parseInt(gold.getText().toString()), b = Integer.parseInt(brains.getText().toString()); String id = selected.appId;
                task(() -> { storage.setCurrency(id, g, b); return "货币已保存，原存档已自动备份"; });
            } catch (Exception e) { error(new IllegalArgumentException("请填写 0～2147483647 的整数")); }
        });
        apply.setEnabled(editable() && currency != null); addButton(money, apply);
        money.addView(text("每次修改前自动备份，可在“存档”页恢复。", 12, palette.muted, false));
    }
    private String duration(long seconds) { return (seconds / 3600) + " 小时 " + ((seconds / 60) % 60) + " 分钟"; }
    private static String formatSimulatedTime(long now, long offset) {
        if (offset < 0 || offset > ZfStorage.MAX_GAME_EPOCH - now / 1000)
            throw new IllegalArgumentException("模拟时间超出游戏支持范围");
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date(now + offset * 1000));
    }
    private void updateSimulatedClock() {
        String current;
        try { current = formatSimulatedTime(System.currentTimeMillis(), settings.optLong("offset", 0)); }
        catch (IllegalArgumentException e) { current = e.getMessage(); }
        simulatedClock.setText("模拟时间：" + current);
    }
    private static long skipSeconds(long hours, int minutes) {
        if (hours < 0 || hours > 100000 || minutes < 0 || minutes > 59 || hours + minutes == 0)
            throw new IllegalArgumentException("请输入小时与 0～59 的分钟，时间需大于零");
        return hours * 3600 + minutes * 60;
    }
    private void launch(long seconds) {
        String id = selected.appId;
        task(() -> {
            storage.advance(id, seconds);
            return null;
        }, () -> startActivity(new Intent(this, MainActivity.class)));
    }
    private void skipDialog() {
        LinearLayout content = vertical(); content.setPadding(dp(24), dp(8), dp(24), dp(8));
        EditText hours = number("小时", settings.optString("skipHours", "6"), false);
        EditText minutes = number("分钟", settings.optString("skipMinutes", "0"), false);
        LinearLayout hourField = vertical(), minuteField = vertical();
        TextView hourLabel = text("小时", 13, palette.muted, false), minuteLabel = text("分钟", 13, palette.muted, false);
        hours.setId(View.generateViewId()); hourLabel.setLabelFor(hours.getId());
        minutes.setId(View.generateViewId()); minuteLabel.setLabelFor(minutes.getId());
        hourField.addView(hourLabel); hourField.addView(hours);
        minuteField.addView(minuteLabel); minuteField.addView(minutes);
        pair(content, hourField, minuteField);
        content.addView(text("跳过时间会累加，普通启动继续使用累计值。", 13, palette.muted, false));
        TextView preview = text("", 14, palette.ink, false); content.addView(preview);
        AlertDialog dialog = dialogBuilder().setTitle("启动并跳过时间").setView(content)
            .setNegativeButton("取消", null).setPositiveButton("启动", null).create();
        skipPreview = () -> {
            long now = System.currentTimeMillis(), offset = settings.optLong("offset", 0);
            String current = "无法读取", after;
            boolean valid = false;
            try {
                current = formatSimulatedTime(now, offset);
                long seconds = skipSeconds(Long.parseLong(hours.getText().toString()), Integer.parseInt(minutes.getText().toString()));
                after = formatSimulatedTime(now, offset + seconds);
                valid = true;
            } catch (NumberFormatException e) { after = "请输入有效的快进时间"; }
            catch (IllegalArgumentException e) { after = e.getMessage(); }
            preview.setText("当前模拟时间：" + current + "\n快进后：" + after);
            Button start = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            if (start != null) start.setEnabled(valid);
        };
        android.text.TextWatcher previewOnEdit = new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                if (skipPreview != null) skipPreview.run();
            }
            public void afterTextChanged(android.text.Editable e) {}
        };
        hours.addTextChangedListener(previewOnEdit); minutes.addTextChangedListener(previewOnEdit);
        dialog.setOnDismissListener(d -> skipPreview = null);
        dialog.setOnShowListener(d -> dialog.getButton(-1).setOnClickListener(v -> {
            try {
                long h = Long.parseLong(hours.getText().toString()); int m = Integer.parseInt(minutes.getText().toString());
                String id = selected.appId; long seconds = skipSeconds(h, m);
                dialog.dismiss(); task(() -> {
                    JSONObject app = storage.settings(id).put("skipHours", h).put("skipMinutes", m);
                    storage.advance(id, seconds, app);
                    return null;
                }, () -> startActivity(new Intent(this, MainActivity.class)));
            } catch (Exception e) { toast("请输入小时与 0～59 的分钟，时间需大于零"); }
        })); dialog.show(); tintDialogButtons(dialog); skipPreview.run();
    }
    private void settingsPage() {
        JSONObject displaySettings = submittedSettings != null ? submittedSettings : settings;
        LinearLayout display = card("画面设置", "按当前版本记忆设置；游戏画面保持比例并适配屏幕。");
        display.addView(text("设备类型", 13, palette.muted, false)); family = spinner(new String[]{"iPhone（推荐）", "iPad"});
        family.setSelection(displaySettings.optString("family", ZfStorage.DEFAULT_FAMILY).equals("ipad") ? 1 : 0); display.addView(family); family.setEnabled(editable());
        display.addView(text("渲染倍率", 13, palette.muted, false));
        String[] scaleChoices = new String[SCALE_PRESETS.length + 1];
        for (int i = 0; i < SCALE_PRESETS.length; i++) scaleChoices[i] = "×" + SCALE_PRESETS[i];
        scaleChoices[SCALE_PRESETS.length] = "自定义";
        scale = spinner(scaleChoices);
        String current = ZfStorage.validScaleOrDefault(displaySettings.optString("scale", ZfStorage.DEFAULT_SCALE));
        int index = Arrays.asList(SCALE_PRESETS).indexOf(current);
        scale.setSelection(index < 0 ? SCALE_PRESETS.length : index); display.addView(scale); scale.setEnabled(editable());
        customScale = number("小数或分数，例如 1.5、3/2", current, true); display.addView(customScale);
        customScale.setVisibility(index < 0 ? View.VISIBLE : View.GONE); customScale.setEnabled(editable());
        resolution = text("", 13, palette.accentText, true); display.addView(resolution);
        AdapterView.OnItemSelectedListener sizes = new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int position, long id) {
                if (p != family && p != scale) return;
                customScale.setVisibility(scale.getSelectedItemPosition() == SCALE_PRESETS.length ? View.VISIBLE : View.GONE);
                updateResolution(); queueSettingsSave();
            }
        }; family.setOnItemSelectedListener(sizes); scale.setOnItemSelectedListener(sizes);
        customScale.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int c, int n) {}
            public void onTextChanged(CharSequence s, int a, int b, int c) { updateResolution(); queueSettingsSave(); }
            public void afterTextChanged(android.text.Editable e) {}
        }); updateResolution();
        display.addView(text("默认 iPhone ×3（1440 × 960）。画面卡顿时可调低倍率；两指缩放由游戏处理。", 12, palette.muted, false));
        LinearLayout timing = card("帧率设置", null);
        fps = spinner(new String[]{"30 FPS", "60 FPS（推荐）", "90 FPS", "120 FPS", "不限帧率", "自定义"});
        String[] rates = {"30", "60", "90", "120", "off"}; current = displaySettings.optString("fps", "60");
        index = Arrays.asList(rates).indexOf(current); fps.setSelection(index < 0 ? 5 : index); timing.addView(fps); fps.setEnabled(editable());
        customFps = number("1～1000 FPS", current.equals("off") ? "60" : current, false); timing.addView(customFps);
        customFps.setVisibility(index < 0 ? View.VISIBLE : View.GONE); customFps.setEnabled(editable());
        fps.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int position, long id) {
                if (p != fps) return;
                customFps.setVisibility(position == 5 ? View.VISIBLE : View.GONE);
                queueSettingsSave();
            }
        });
        customFps.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int c, int n) {}
            public void onTextChanged(CharSequence s, int a, int b, int c) { queueSettingsSave(); }
            public void afterTextChanged(android.text.Editable e) {}
        });
        fix = new Switch(this); fix.setText("高速帧率修复（推荐开启）"); fix.setTextSize(14); fix.setTextColor(palette.ink);
        fix.setThumbTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{palette.accentText, palette.muted}));
        fix.setTrackTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{ZfAppearance.mix(palette.accent, palette.surface, 0.55), palette.line}));
        fix.setChecked(displaySettings.optBoolean("fix", true)); fix.setEnabled(editable()); fix.setPadding(0, dp(14), 0, dp(8)); timing.addView(fix);
        fix.setOnCheckedChangeListener((button, checked) -> queueSettingsSave());
        timing.addView(text("关闭修复可能让游戏无法达到设定帧率。提高帧率不会加快游戏时间。", 12, palette.muted, false));
        settingsStatus = text(submittedSettings == null ? "已保存 · 下次启动生效" : "正在保存…", 12, palette.accentText, false);
        timing.addView(settingsStatus);
    }
    private void queueSettingsSave() {
        if (!editable() || family == null || scale == null || fps == null || fix == null) return;
        settingsHandler.removeCallbacks(settingsSaveRequest);
        pendingSettings = null;
        JSONObject reference = submittedSettings != null ? submittedSettings : settings;
        try {
            String scaleText = scaleValue(), fpsText = fpsValue();
            ZfStorage.scale(scaleText);
            if (!fpsText.equals("off")) {
                if (!fpsText.matches("[0-9]+")) throw new IllegalArgumentException("请输入 1～1000 的整数帧率");
                int rate = Integer.parseInt(fpsText);
                if (rate < 1 || rate > 1000) throw new IllegalArgumentException("请输入 1～1000 的整数帧率");
            }
            JSONObject draft = new JSONObject()
                .put("family", family.getSelectedItemPosition() == 1 ? "ipad" : "iphone")
                .put("scale", scaleText).put("fps", fpsText).put("fix", fix.isChecked());
            if (draft.optString("family").equals(reference.optString("family", ZfStorage.DEFAULT_FAMILY))
                    && draft.optString("scale").equals(reference.optString("scale", ZfStorage.DEFAULT_SCALE))
                    && draft.optString("fps").equals(reference.optString("fps", "60"))
                    && draft.optBoolean("fix", true) == reference.optBoolean("fix", true)) return;
            pendingSettings = draft;
            pendingSettingsId = selected.appId;
            settingsHandler.postDelayed(settingsSaveRequest, 250);
        } catch (Exception e) {
            if (settingsStatus != null) settingsStatus.setText("输入值尚未有效，因此未保存");
        }
    }
    private void flushSettingsSave() {
        if (pendingSettings == null) return;
        settingsHandler.removeCallbacks(settingsSaveRequest);
        JSONObject draft = pendingSettings;
        String id = pendingSettingsId;
        pendingSettings = null;
        submittedSettings = draft;
        if (settingsStatus != null) settingsStatus.setText("正在保存…");
        worker.execute(() -> {
            Exception failure = null;
            JSONObject saved = null;
            try (ZfStorage.Lease ignored = storage.lock()) {
                saved = storage.settings(id);
                for (Iterator<String> keys = draft.keys(); keys.hasNext();) {
                    String key = keys.next();
                    saved.put(key, draft.get(key));
                }
                storage.settings(id, saved);
            }
            catch (Exception e) { failure = e; }
            final Exception problem = failure;
            final JSONObject persisted = saved;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                if (problem == null && selected != null && id.equals(selected.appId)) settings = persisted;
                if (submittedSettings == draft) {
                    submittedSettings = null;
                    if (settingsStatus != null && pendingSettings == null)
                        settingsStatus.setText(problem == null ? "已保存 · 下次启动生效" : "保存失败");
                }
                if (problem != null) error(problem);
            });
        });
    }
    private String scaleValue() {
        int index = scale.getSelectedItemPosition();
        return index == SCALE_PRESETS.length ? customScale.getText().toString().trim() : SCALE_PRESETS[index];
    }
    private String fpsValue() { String[] v = {"30", "60", "90", "120", "off"}; return fps.getSelectedItemPosition() == 5 ? customFps.getText().toString().trim() : v[fps.getSelectedItemPosition()]; }
    private void updateResolution() {
        try {
            double factor = ZfStorage.scale(scaleValue()); boolean ipad = family.getSelectedItemPosition() == 1;
            resolution.setText("渲染尺寸 " + Math.round((ipad ? 1024 : 480) * factor) + " × " + Math.round((ipad ? 768 : 320) * factor));
        } catch (Exception e) { resolution.setText("请输入有效倍率"); }
    }
    private void savePage() {
        LinearLayout current = card("当前存档", selected.name);
        current.addView(text(currency == null ? saveMessage : "金币 " + currency.gold + " · 脑子 " + currency.brains, 15, palette.ink, true));
        current.addView(text("累计跳过 " + duration(settings.optLong("offset", 0)), 13, palette.muted, false));
        Button backup = button("新建完整备份", true, () -> { String id = selected.appId; task(() -> { storage.backup(id, "手动"); return "完整备份已创建"; }); });
        backup.setEnabled(editable() && currency != null); addButton(current, backup);
        Button importButton = button("导入存档或备份", false, () -> { pendingId = selected.appId; chooseFile(IMPORT_SAVE); });
        importButton.setEnabled(editable()); addButton(current, importButton);
        current.addView(text("支持 ZF 完整备份 .zip 和 saveGame.bin2。完整备份包含进度、资料和累计跳过时间。", 12, palette.muted, false));
        LinearLayout list = card("备份记录", backups.isEmpty() ? "尚无备份。修改货币和恢复进度前会自动备份。" : "点击记录可恢复、导出或删除。");
        for (File file : backups) {
            String title = file.getName().replaceFirst("_[^_]+\\.zip$", "");
            Button item = button(title, false, () -> backupActions(file)); item.setEnabled(!busy); addButton(list, item);
        }
    }
    private void backupActions(File file) {
        String id = selected.appId;
        dialogBuilder().setTitle("存档备份").setItems(new String[]{"恢复这份备份", "导出到手机文件", "删除这份备份"}, (d, which) -> {
            if (which == 0) {
                if (!editable()) { toast("请先退出游戏"); return; }
                dialogBuilder().setTitle("恢复备份？").setMessage("将恢复进度和累计跳过时间。当前进度会先自动备份。")
                    .setNegativeButton("取消", null).setPositiveButton("恢复", (a, b) -> task(() -> {
                        try (InputStream in = new FileInputStream(file)) { storage.restore(id, in); } return "备份已恢复";
                    })).show();
            } else if (which == 1) {
                exportFile = file;
                startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/zip").putExtra(Intent.EXTRA_TITLE, "ZF-" + file.getName()), EXPORT_SAVE);
            } else {
                if (!editable()) { toast("请先退出游戏"); return; }
                dialogBuilder().setTitle("删除这份备份？").setMessage("当前游戏进度不受影响。")
                    .setNegativeButton("取消", null).setPositiveButton("删除", (a, b) -> task(() -> { storage.deleteBackup(id, file); return "备份已删除"; })).show();
            }
        }).show();
    }
    private void chooseFile(int request) {
        startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), request);
    }
    private String fileName(Uri uri) {
        try (android.database.Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                String name = c.getString(0);
                if (name != null && !name.trim().isEmpty()) return name;
            }
        } catch (Exception ignored) {}
        return "导入文件";
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (request == IMPORT_IPA) task(() -> {
            String name = fileName(uri);
            try (InputStream in = getContentResolver().openInputStream(uri)) { storage.importIpa(in, name); } return "IPA 已导入并选中";
        });
        else if (request == IMPORT_SAVE) {
            final String id = pendingId;
            dialogBuilder().setTitle("导入存档？").setMessage("文件：" + fileName(uri) + "\n当前进度会先自动备份。")
                .setNegativeButton("取消", null).setPositiveButton("导入", (d, w) -> task(() -> {
                    try (BufferedInputStream in = new BufferedInputStream(getContentResolver().openInputStream(uri))) {
                        in.mark(4); int a = in.read(), b = in.read(); in.reset();
                        if (a == 'P' && b == 'K') storage.restore(id, in); else storage.importSave(id, in);
                    } return "存档已导入";
                })).show();
        } else if (request == EXPORT_SAVE && exportFile != null) {
            File source = exportFile;
            task(() -> {
                try (InputStream in = new FileInputStream(source); OutputStream out = getContentResolver().openOutputStream(uri, "wt")) {
                    if (out == null) throw new IOException("无法打开导出位置"); ZfStorage.copy(in, out, ZfStorage.MAX_BACKUP_ARCHIVE_BYTES);
                } return "备份已导出";
            });
        }
    }
    private void error(Exception e) {
        dialogBuilder().setTitle("操作未完成").setMessage(e.getMessage() == null ? e.toString() : e.getMessage())
            .setPositiveButton("知道了", null).show();
    }
    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_LONG).show(); }

    static void showBundledWarning(Activity activity, String detail) {
        AlertDialog.Builder builder = activity instanceof ManagerActivity ? ((ManagerActivity)activity).dialogBuilder() : new AlertDialog.Builder(activity);
        builder
            .setTitle("内置 IPA 校验提醒")
            .setMessage(detail + "\n\n你拿到的可能是改版。项目正式版可从以下地址免费下载。\n" + PROJECT_URL)
            .setPositiveButton("知道了", null).show();
    }

    // --- free / open-source statement --------------------------------------

    private void showNoticeIfNeeded() {
        boolean firstRun = !NOTICE_VERSION.equals(getPreferences(MODE_PRIVATE).getString("notice_version", ""));
        // Recorded before showing, so a crash while the dialog is up does not
        // make the next launch present itself as the first one again. The
        // preference no longer decides whether the dialog appears -- that is
        // every launch, see the note beside NOTICE_VERSION.
        getPreferences(MODE_PRIVATE).edit().putString("notice_version", NOTICE_VERSION).apply();
        showProjectNotice(firstRun);
    }

    private void showProjectNotice(boolean firstRun) {
        String message =
            "本软件完全免费、开源，任何人都可以从下面这个官方地址免费下载，不需要付款，也没有付费版。\n\n"
            + PROJECT_URL + "\n"
            + "交流群 QQ " + QQ_GROUP + "\n\n"
            + "如果你是花钱买到这个软件包的：你买到的只是一份免费的公开文件，请尽快向卖家申请退款。"
            + "本项目不通过任何中间渠道销售，也不对转卖渠道提供任何支持。\n\n"
            + "· 基于 touchHLE 模拟器制作，非官方同人作品；模拟器部分遵循 MPL-2.0 许可。\n"
            + "· 游戏素材版权归原开发商所有，本项目仅供个人学习与怀旧使用。\n"
            + "· 发行包不含任何玩家存档，首次进入游戏会新建进度。";
        noticeDialog = dialogBuilder()
            .setTitle(firstRun ? "欢迎使用 · 免费开源声明" : "免费开源声明")
            .setMessage(message)
            .setPositiveButton("打开项目主页", (dialog, which) -> openProjectUrl())
            .setNeutralButton("复制链接", (dialog, which) -> {
                ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                clipboard.setPrimaryClip(ClipData.newPlainText("Zombie Farm", PROJECT_URL));
                toast("官方地址已复制");
            })
            .setNegativeButton(firstRun ? "我知道了，开始使用" : "关闭", null)
            .show();
    }

    private void openProjectUrl() {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(PROJECT_URL))); }
        catch (Exception e) { toast("无法打开浏览器，请手动访问：" + PROJECT_URL); }
    }

    // --- signature self-check ----------------------------------------------

    private void verifySignature() {
        String actual;
        try { actual = signatureOfSelf(this); }
        catch (Exception e) { return; }             // never block the app on this
        if (actual == null || actual.equalsIgnoreCase(OFFICIAL_CERT)) return;
        dialogBuilder()
            .setTitle("检测到非官方修改版本")
            .setMessage("这个安装包的签名与官方发布版不一致，说明它被动过（例如塞入广告、替换内容）后重新打包。\n\n"
                + "当前签名：" + actual + "\n\n官方签名：" + OFFICIAL_CERT
                + "\n\n它可能是别人转卖的改版，建议从官方地址重新下载。")
            .setPositiveButton("打开项目主页", (dialog, which) -> openProjectUrl())
            .setNegativeButton("继续使用", null)
            .show();
    }

    static String signatureOfSelf(Activity activity) throws Exception {
        PackageManager pm = activity.getPackageManager();
        String name = activity.getPackageName();
        if (Build.VERSION.SDK_INT >= 28) {
            PackageInfo info = pm.getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES);
            if (info.signingInfo == null) return null;
            Signature[] signatures = info.signingInfo.hasMultipleSigners()
                ? info.signingInfo.getApkContentsSigners()
                : info.signingInfo.getSigningCertificateHistory();
            return signatures == null || signatures.length == 0 ? null : sha256Hex(signatures[0].toByteArray());
        }
        PackageInfo info = pm.getPackageInfo(name, PackageManager.GET_SIGNATURES);
        return info.signatures == null || info.signatures.length == 0 ? null : sha256Hex(info.signatures[0].toByteArray());
    }

    private static String sha256Hex(byte[] data) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(data);
        StringBuilder text = new StringBuilder(hash.length * 2);
        for (byte value : hash) text.append(String.format(Locale.ROOT, "%02x", value));
        return text.toString();
    }
}
