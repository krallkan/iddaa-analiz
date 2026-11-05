package com.krallkan.iddaaanaliz;

import android.app.Activity;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/** Günlük raporu (GitHub Pages) gösterir. Ağır hesaplar GitHub Actions'ta yapılır. */
public class MainActivity extends Activity {
    private WebView web;
    private static final String ERROR_HTML =
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        + "<body style='font-family:sans-serif;padding:24px'><h3>Rapor yüklenemedi</h3>"
        + "<p>İnternet bağlantınızı kontrol edin. Uygulamayı kapatıp açarak yeniden deneyebilirsiniz.</p></body></html>";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(0xFF0D1220);
        getWindow().setNavigationBarColor(0xFF0F1528);
        web = new WebView(this);
        web.setBackgroundColor(0xFF0D1220);
        FrameLayout root = new FrameLayout(this);
        root.addView(web);
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);           // etkileşimli arayüz (sekmeler, kupon)
        s.setDomStorageEnabled(true);           // kupon ve son rapor cihazda saklanır (çevrimdışı görüntüleme)
        s.setCacheMode(isOnline() ? WebSettings.LOAD_NO_CACHE : WebSettings.LOAD_CACHE_ELSE_NETWORK);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                // Rapor sitesi içinde kal; dış bağlantıları (haber kaynakları) tarayıcıda aç
                if (u.toString().startsWith(BuildConfig.REPORT_URL)) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, u));
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) view.loadData(ERROR_HTML, "text/html; charset=utf-8", "UTF-8");
            }
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(BuildConfig.REPORT_URL + "app/");
    }

    private boolean isOnline() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm == null || cm.getActiveNetwork() == null) return false;
        NetworkCapabilities c = cm.getNetworkCapabilities(cm.getActiveNetwork());
        return c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Arayüzün kendi yenileme düğmesi var; kupon/sekme durumu kaybolmasın diye otomatik yeniden yükleme yok
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
