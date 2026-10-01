package io.github.kingsworksub.topics

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.OffsetDateTime
import java.time.ZoneOffset

data class Topic(
    val id: String,
    val status: String,
    val category: String,
    val theme: String,
    val angle: String,
    val articleType: String,
    val keywords: List<String>,
    val score: Int,
    val sourceOfIdea: String,
    val created: String,
    val slug: String?,
)

data class PipelineStatus(
    val engineToday: String,
    val todayPosts: Int,
    val dailyLimit: Int,
    val consecutiveFailures: Int,
    val lastResult: String,
    val updated: String,
)

data class Snapshot(
    val topics: List<Topic>,
    val categories: Map<String, String>,
    val skipped: Set<String>,
    val status: PipelineStatus?,
    val queueUpdated: String,
)

/** Reads the topic queue from GitHub and records deletions as scripts/topic-skips/<id>.json. */
class GitHubRepo(private val token: String?) {
    private val base = "https://api.github.com/repos/$OWNER/$REPO/contents"

    private fun request(path: String, method: String = "GET", body: String? = null, raw: Boolean = true): Pair<Int, String> {
        val conn = URL("$base/$path").openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 15000
        conn.readTimeout = 20000
        conn.setRequestProperty("Accept", if (raw) "application/vnd.github.raw+json" else "application/vnd.github+json")
        conn.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
        conn.setRequestProperty("User-Agent", "BlogTopicsApp")
        if (!token.isNullOrBlank()) conn.setRequestProperty("Authorization", "Bearer $token")
        if (body != null) {
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        conn.disconnect()
        return code to text
    }

    private fun getRaw(path: String): String? {
        val (code, text) = request("$path?ref=main")
        return when (code) {
            200 -> text
            404 -> null
            else -> throw IOException("GitHub $code: ${text.take(200)}")
        }
    }

    fun load(): Snapshot {
        val queue = JSONObject(getRaw("scripts/topics-queue.json") ?: """{"items":[]}""")
        val items = queue.optJSONArray("items") ?: JSONArray()
        val topics = (0 until items.length()).map { i ->
            val o = items.getJSONObject(i)
            val kw = o.optJSONArray("keywords") ?: JSONArray()
            Topic(
                id = o.optString("id"),
                status = o.optString("status"),
                category = o.optString("category"),
                theme = o.optString("theme"),
                angle = o.optString("angle"),
                articleType = o.optString("article_type"),
                keywords = (0 until kw.length()).map { kw.optString(it) },
                score = o.optJSONObject("score")?.optInt("total") ?: 0,
                sourceOfIdea = o.optString("source_of_idea"),
                created = o.optString("created"),
                slug = o.optString("slug").ifBlank { null },
            )
        }
        val cats = mutableMapOf<String, String>()
        getRaw("scripts/category-plan.json")?.let { txt ->
            val arr = JSONArray(txt)
            for (i in 0 until arr.length()) {
                val c = arr.getJSONObject(i)
                cats[c.optString("id")] = c.optString("name")
            }
        }
        val skipped = mutableSetOf<String>()
        val (code, list) = request("scripts/topic-skips?ref=main", raw = false)
        if (code == 200) {
            val arr = JSONArray(list)
            for (i in 0 until arr.length()) {
                val name = arr.getJSONObject(i).optString("name")
                if (name.endsWith(".json")) skipped += name.removeSuffix(".json")
            }
        }
        val status = getRaw("scripts/pipeline-status.json")?.let { txt ->
            val s = JSONObject(txt)
            PipelineStatus(
                engineToday = s.optString("engine_today"),
                todayPosts = s.optInt("today_posts"),
                dailyLimit = s.optInt("daily_limit", 8),
                consecutiveFailures = s.optInt("consecutive_failures"),
                lastResult = s.optString("last_result"),
                updated = s.optString("updated"),
            )
        }
        return Snapshot(topics, cats, skipped, status, queue.optString("updated"))
    }

    /** Creates scripts/topic-skips/<id>.json. The pipeline then marks the topic deleted and never posts it. */
    fun skip(topic: Topic) {
        require(!token.isNullOrBlank()) { "GitHub トークンが未設定です（右上の設定から入力）" }
        val payload = JSONObject()
            .put("id", topic.id)
            .put("theme", topic.theme)
            .put("deleted_at", OffsetDateTime.now(ZoneOffset.ofHours(9)).withNano(0).toString())
            .put("by", "android")
            .toString(1)
        val body = JSONObject()
            .put("message", "Skip topic ${topic.id} (Android app)")
            .put("content", Base64.encodeToString(payload.toByteArray(Charsets.UTF_8), Base64.NO_WRAP))
            .put("branch", "main")
            .toString()
        val (code, text) = request("scripts/topic-skips/${topic.id}.json", "PUT", body, raw = false)
        if (code == 422 && text.contains("sha")) return // already skipped
        if (code !in 200..299) throw IOException("削除に失敗しました（GitHub $code）: ${text.take(160)}")
    }

    companion object {
        const val OWNER = "kingsworksub-jpg"
        const val REPO = "kingsworksub-jpg.github.io"
    }
}
