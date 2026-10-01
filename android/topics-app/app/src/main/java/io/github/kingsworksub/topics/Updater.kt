package io.github.kingsworksub.topics

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.core.content.pm.PackageInfoCompat
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** Self-update from the topics-app-latest GitHub release (same signing key, so it installs over the old app). */
object Updater {
    fun installedVersionCode(context: Context): Long =
        PackageInfoCompat.getLongVersionCode(context.packageManager.getPackageInfo(context.packageName, 0))

    fun installedVersionName(context: Context): String =
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "?"

    /** Downloads the APK into the cache. Runs on a background thread. */
    fun download(context: Context, url: String): File {
        val dir = File(context.cacheDir, "apk").apply { mkdirs() }
        val out = File(dir, "blog-topics.apk")
        var conn = URL(url).openConnection() as HttpURLConnection
        var hops = 0
        while (conn.responseCode in 300..399 && hops < 5) {
            val next = conn.getHeaderField("Location")
            conn.disconnect()
            conn = URL(next).openConnection() as HttpURLConnection
            hops++
        }
        if (conn.responseCode != 200) throw IllegalStateException("ダウンロードに失敗しました（${conn.responseCode}）")
        conn.inputStream.use { input -> out.outputStream().use { input.copyTo(it) } }
        conn.disconnect()
        return out
    }

    /** Returns false (after opening the settings screen) if the user must first allow installs from this app. */
    fun install(context: Context, apk: File): Boolean {
        if (!context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", apk)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return true
    }
}
