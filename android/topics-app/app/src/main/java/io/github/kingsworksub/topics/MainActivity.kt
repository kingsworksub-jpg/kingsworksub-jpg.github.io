package io.github.kingsworksub.topics

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val PREFS = "blog_topics"
private const val KEY_TOKEN = "github_token"

private val STATUS_LABELS = linkedMapOf(
    "approved" to "承認済み",
    "in_progress" to "投稿中",
    "published" to "公開済み",
    "failed" to "失敗",
    "rejected" to "不採用",
    "hold" to "保留",
    "deleted" to "削除済み",
)
private val TYPE_LABELS = mapOf(
    "deep-dive" to "深掘り", "comparison" to "比較", "theme" to "テーマ",
    "styling" to "スタイリング", "guide" to "ガイド",
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF2F6F8F))) {
                TopicsScreen(
                    initialToken = prefs.getString(KEY_TOKEN, "") ?: "",
                    saveToken = { prefs.edit().putString(KEY_TOKEN, it.trim()).apply() },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TopicsScreen(initialToken: String, saveToken: (String) -> Unit) {
    var token by remember { mutableStateOf(initialToken) }
    var snapshot by remember { mutableStateOf<Snapshot?>(null) }
    var loading by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("approved") }
    var confirm by remember { mutableStateOf<Topic?>(null) }
    var showSettings by remember { mutableStateOf(initialToken.isBlank()) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    fun refresh() {
        if (loading) return
        loading = true
        scope.launch {
            try {
                snapshot = withContext(Dispatchers.IO) { GitHubRepo(token).load() }
            } catch (e: Exception) {
                snackbar.showSnackbar("読み込みに失敗しました: ${e.message}")
            } finally {
                loading = false
            }
        }
    }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { refresh() }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000)
            refresh()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("ブログのネタ") },
                actions = {
                    IconButton(onClick = { refresh() }) { Icon(Icons.Filled.Refresh, "更新") }
                    IconButton(onClick = { showSettings = true }) { Icon(Icons.Filled.Settings, "設定") }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth()) else Spacer(Modifier.height(4.dp))
            val snap = snapshot
            snap?.status?.let { StatusCard(it, snap) }
            LazyRow(
                Modifier.padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                val keys = listOf("approved", "in_progress", "published", "deleted", "all")
                items(keys) { k ->
                    val n = snap?.topics?.count { k == "all" || effectiveStatus(it, snap) == k } ?: 0
                    FilterChip(
                        selected = filter == k,
                        onClick = { filter = k },
                        label = { Text("${STATUS_LABELS[k] ?: "すべて"} $n") },
                    )
                }
            }
            val shown = snap?.topics
                ?.filter { filter == "all" || effectiveStatus(it, snap) == filter }
                ?.sortedWith(compareByDescending<Topic> { it.created }.thenBy { it.id })
                ?: emptyList()
            if (snap != null && shown.isEmpty()) {
                Text("該当するネタはありません", Modifier.padding(24.dp), color = Color.Gray)
            }
            LazyColumn(
                Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
            ) {
                items(shown, key = { it.id }) { t ->
                    TopicCard(
                        topic = t,
                        categoryName = snap?.categories?.get(t.category) ?: t.category,
                        status = effectiveStatus(t, snap!!),
                        onDelete = { confirm = t },
                    )
                }
            }
        }
    }

    confirm?.let { t ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("このネタを削除しますか？") },
            text = { Text("「${t.theme}」\n\n削除すると、投稿パイプラインはこのネタをスキップします（GitHub に削除の記録を残します）。") },
            confirmButton = {
                TextButton(onClick = {
                    confirm = null
                    scope.launch {
                        try {
                            withContext(Dispatchers.IO) { GitHubRepo(token).skip(t) }
                            snackbar.showSnackbar("削除しました。次の投稿からスキップされます")
                            refresh()
                        } catch (e: Exception) {
                            snackbar.showSnackbar(e.message ?: "削除に失敗しました")
                        }
                    }
                }) { Text("削除") }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("キャンセル") } },
        )
    }

    if (showSettings) {
        var input by remember { mutableStateOf(token) }
        AlertDialog(
            onDismissRequest = { showSettings = false },
            title = { Text("GitHub トークン") },
            text = {
                Column {
                    Text("ネタの削除に使います（閲覧だけならトークンなしで使えます）。" +
                        "対象リポジトリ ${GitHubRepo.OWNER}/${GitHubRepo.REPO} に Contents の読み書き権限を付けた fine-grained トークンを入力してください。")
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        label = { Text("github_pat_...") },
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    token = input.trim()
                    saveToken(token)
                    showSettings = false
                    refresh()
                }) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { showSettings = false }) { Text("閉じる") } },
        )
    }
}

/** A topic deleted in the app shows as deleted immediately, before the pipeline has synced it. */
private fun effectiveStatus(t: Topic, snap: Snapshot): String =
    if (t.id in snap.skipped && t.status in setOf("approved", "hold", "failed")) "deleted" else t.status

@Composable
private fun StatusCard(s: PipelineStatus, snap: Snapshot) {
    Card(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFEFF5F8)),
    ) {
        Column(Modifier.padding(12.dp)) {
            val engine = if (s.engineToday == "big-pickle") "big-pickle" else "Claude Code"
            Text("今日の投稿 ${s.todayPosts} / ${s.dailyLimit}　・　今日のモデル: $engine", fontWeight = FontWeight.Bold)
            if (s.consecutiveFailures >= 3) {
                Text("連続失敗 ${s.consecutiveFailures} 回のため自動投稿は停止中です", color = Color(0xFFB3261E))
            } else if (s.consecutiveFailures > 0) {
                Text("連続失敗 ${s.consecutiveFailures} 回", color = Color(0xFFB3261E))
            }
            if (s.lastResult.isNotBlank()) Text("直近: ${s.lastResult}", style = MaterialTheme.typography.bodySmall)
            Text("キュー更新: ${snap.queueUpdated.take(16).replace('T', ' ')}", style = MaterialTheme.typography.bodySmall, color = Color.Gray)
        }
    }
}

@Composable
private fun TopicCard(topic: Topic, categoryName: String, status: String, onDelete: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                AssistChip(onClick = {}, label = { Text(categoryName) })
                Spacer(Modifier.padding(3.dp))
                Text(
                    "${TYPE_LABELS[topic.articleType] ?: topic.articleType}・${topic.score}点・${STATUS_LABELS[status] ?: status}",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.weight(1f),
                )
                if (status in setOf("approved", "hold", "failed")) {
                    IconButton(onClick = onDelete) { Icon(Icons.Filled.Delete, "削除") }
                }
            }
            Text(topic.theme, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            if (topic.angle.isNotBlank()) {
                Text(topic.angle, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
            }
            if (topic.keywords.isNotEmpty()) {
                Text(topic.keywords.joinToString("　"), style = MaterialTheme.typography.bodySmall, color = Color.Gray,
                    modifier = Modifier.padding(top = 4.dp))
            }
            Text(
                listOfNotNull(topic.id, topic.created, if (topic.sourceOfIdea == "user") "持ち込み" else null, topic.slug)
                    .joinToString("・"),
                style = MaterialTheme.typography.labelSmall,
                color = Color.Gray,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}
