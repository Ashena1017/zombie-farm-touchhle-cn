package org.touchhle.android

import android.webkit.WebView

class MobileManagerActivity : TauriActivity() {
    private var managerView: WebView? = null

    override fun onWebViewCreate(webView: WebView) {
        super.onWebViewCreate(webView)
        managerView = webView
    }

    @Deprecated("Handles the manager's local dialogs before leaving the activity")
    override fun onBackPressed() {
        val view = managerView
        if (view == null) finish()
        else view.evaluateJavascript("window.managerBack?.() === true") {
            if (it != "true") finish()
        }
    }
}
