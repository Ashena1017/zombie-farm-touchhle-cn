/* This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.ProgressBar;
import android.widget.Toast;
import java.io.IOException;
import java.util.UUID;
import org.json.JSONObject;

/** Verify and prepare the game in its own process before SDL starts its native thread. */
public class MainActivity extends Activity {
    static final int REQUEST_GAME = 713;
    static final int WARNING = RESULT_FIRST_USER;
    private static Prepared pending; // Published and consumed only on the main thread.

    static Intent request(Activity caller, String id, int hours, int minutes, boolean remember, boolean allowModified) {
        return new Intent(caller, MainActivity.class).putExtra("appId", id)
            .putExtra("requestId", UUID.randomUUID().toString()).putExtra("hours", hours)
            .putExtra("minutes", minutes).putExtra("remember", remember).putExtra("allowModified", allowModified);
    }

    static final class Prepared {
        final MainActivity owner;
        final ZfStorage storage;
        final ZfStorage.Lease lease;
        final String id, warning;
        final JSONObject settings;
        final String[] arguments;
        final boolean save;

        Prepared(MainActivity owner, ZfStorage storage, ZfStorage.Lease lease, ZfIpa ipa,
                 JSONObject settings, String warning, boolean save) {
            this.owner = owner; this.storage = storage; this.lease = lease; this.id = ipa.appId;
            this.settings = settings; this.warning = warning; this.save = save;
            arguments = new String[]{ipa.file.getPath(),
                "--device-family=" + settings.optString("family", ZfStorage.DEFAULT_FAMILY),
                "--scale-hack=" + ZfStorage.validScaleOrDefault(settings.optString("scale", ZfStorage.DEFAULT_SCALE)),
                "--fps-limit=" + settings.optString("fps", "60")};
        }
        void commit() throws Exception {
            if (save) storage.settings(id, settings);
        }
    }

    static Prepared takePrepared() {
        Prepared launch = pending;
        pending = null;
        return launch;
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(new ProgressBar(this));
        // Only this app's startActivityForResult calls may request clock changes.
        boolean internal = getPackageName().equals(getCallingPackage());
        if (FarmActivity.running) {
            if (internal) complete(RESULT_CANCELED, "游戏已在运行");
            else {
                startActivity(new Intent(this, FarmActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
                finish();
            }
            return;
        }
        Intent request = internal ? getIntent() : new Intent();
        new Thread(() -> prepare(request, internal), "farm-start").start();
    }

    private void prepare(Intent request, boolean internal) {
        ZfStorage.Lease lease = null;
        try {
            ZfStorage storage = new ZfStorage(this);
            lease = storage.lock();
            String warning = storage.ensureBundled();
            if (internal && !request.getBooleanExtra("allowModified", false)) {
                if (!ManagerActivity.OFFICIAL_CERT.equalsIgnoreCase(ManagerActivity.signatureOfSelf(this)))
                    warning = (warning == null ? "" : warning + "\n") + "安装包签名与官方版本不一致。";
                if (warning != null) {
                    String message = warning;
                    runOnUiThread(() -> complete(WARNING, message));
                    return;
                }
            }
            ZfIpa ipa = storage.selected();
            JSONObject settings = storage.settings(ipa.appId);
            boolean save = false;
            if (internal) {
                if (!ipa.appId.equals(request.getStringExtra("appId"))) throw new IOException("所选游戏版本已改变");
                String token = request.getStringExtra("requestId");
                int hours = request.getIntExtra("hours", 0), minutes = request.getIntExtra("minutes", 0);
                if (token == null || hours < 0 || hours > 100000 || minutes < 0 || minutes > 59)
                    throw new IOException("无效的启动请求");
                if (!token.equals(settings.optString("lastLaunch")) && (hours != 0 || minutes != 0 || request.getBooleanExtra("remember", false))) {
                    settings.put("offset", ZfStorage.advancedOffset(settings.optLong("offset", 0), hours * 3600L + minutes * 60L));
                    if (request.getBooleanExtra("remember", false)) settings.put("skipHours", hours).put("skipMinutes", minutes);
                    settings.put("lastLaunch", token);
                    save = true;
                }
            }
            android.system.Os.setenv("TOUCHHLE_TIME_OFFSET_SECONDS", Long.toString(settings.optLong("offset", 0)), true);
            android.system.Os.setenv("TOUCHHLE_ANDROID_RUN_LOOP_FIX", settings.optBoolean("fix", true) ? "1" : "0", true);
            Prepared launch = new Prepared(this, storage, lease, ipa, settings, warning, save);
            runOnUiThread(() -> openGame(launch));
            lease = null; // The prepared launch now owns the lock.
        } catch (Exception e) {
            runOnUiThread(() -> complete(RESULT_CANCELED, e.toString()));
        } finally {
            closeLease(lease);
        }
    }

    private void openGame(Prepared launch) {
        if (isFinishing() || isDestroyed()) { closeLease(launch.lease); return; }
        pending = launch;
        try { startActivity(new Intent(this, FarmActivity.class)); }
        catch (RuntimeException e) { takePrepared(); closeLease(launch.lease); complete(RESULT_CANCELED, e.toString()); }
    }

    private static void closeLease(ZfStorage.Lease lease) {
        if (lease != null) try { lease.close(); } catch (IOException ignored) {}
    }

    @Override protected void onDestroy() {
        if (pending != null && pending.owner == this) closeLease(takePrepared().lease);
        super.onDestroy();
    }

    void complete(int code, String detail) {
        if (detail != null && getCallingPackage() == null) Toast.makeText(this, detail, Toast.LENGTH_LONG).show();
        setResult(code, new Intent().putExtra("detail", detail));
        finish();
    }
}
