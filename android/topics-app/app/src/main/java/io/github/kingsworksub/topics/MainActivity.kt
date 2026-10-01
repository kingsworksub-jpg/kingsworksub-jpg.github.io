package io.github.kingsworksub.topics

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
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
import androidx.compose.ui.platform.LocalContext
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
    "requested" to "リクエスト中",
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
    val context = LocalContext.current
    var token by remember { mutableStateOf(initialToken) }
    var snapshot by remember { mutableStateOf<Snapshot?>(null) }
    var loading by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("approved") }
    var confirm by remember { mutableStateOf<Topic?>(null) }
    var showSettings by remember { mutableStateOf(initialToken.isBlank()) }
    var showAdd by remember { mutableStateOf(false) }
    var menuOpen by remember { mutableStateOf(false) }
    var newer by remember { mutableStateOf<Release?>(null) }
    var updating by remember { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val installed = remember { Updater.installedVersionCode(context) }

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

    fun checkUpdate(manual: Boolean) {
        scope.launch {
            try {
                val rel = withContext(Dispatchers.IO) { GitHubRepo(token).latestRelease() }
                if (rel != null && rel.versionCode > installed) {
                    newer = rel
                } else if (manual) {
                    snackbar.showSnackbar("最新版です（${Updater.installedVersionName(context)}）")
                }
            } catch (e: Exception) {
                if (manual) snackbar.showSnackbar("更新の確認に失敗しました: ${e.message}")
            }
        }
    }

    fun runUpdate(rel: Release) {
        if (updating) return
        updating = true
        scope.launch {
            try {
                snackbar.showSnackbar("新しいバージョン ${rel.versionName} をダウンロードしています…")
                val apk = withContext(Dispatchers.IO) { Updater.download(context, rel.apkUrl) }
                if (!Updater.install(context, apk)) {
                    snackbar.showSnackbar("「このアプリからのインストールを許可」をオンにしてから、もう一度「アプリを更新」を押してください")
                }
            } catch (e: Exception) {
                snackbar.showSnackbar("更新に失敗しました: ${e.message}")
            } finally {
                updating = false
            }
        }
    }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { refresh() }
    LaunchedEffect(Unit) {
        checkUpdate(manual = false)
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
                    IconButton(onClick = { menuOpen = true }) { Icon(Icons.Filled.MoreVert, "メニュー") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        DropdownMenuItem(
                            text = { Text("アプリを更新") },
                            onClick = {
                                menuOpen = false
                                val rel = newer
                                if (rel != null) runUpdate(rel) else checkUpdate(manual = true)
                            },
                        )
                        DropdownMenuItem(text = { Text("GitHub トークン") }, onClick = { menuOpen = false; showSettings = true })
                        DropdownMenuItem(
                            text = { Text("バージョン ${Updater.installedVersionName(context)}", color = Color.Gray) },
                            onClick = { menuOpen = false },
                        )
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showAdd = true }) { Icon(Icons.Filled.Add, "ネタを追加") }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (loading || updating) LinearProgressIndicator(Modifier.fillMaxWidth()) else Spacer(Modifier.height(4.dp))
            newer?.let { rel ->
                Card(
                    Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF4E0)),
                ) {
                    Row(Modifier.padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("新しいバージョン ${rel.versionName} があります", modifier = Modifier.weight(1f))
                        TextButton(onClick = { runUpdate(rel) }) { Text("更新する") }
                    }
                }
            }
            val snap = snapshot
            snap?.status?.let { StatusCard(it, snap) }
            val rows = snap?.let { allRows(it) } ?: emptyList()
            LazyRow(
                Modifier.padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                val keys = listOf("approved", "requested", "in_progress", "published", "deleted", "all")
                items(keys) { k ->
                    val n = rows.count { k == "all" || it.second == k }
                    FilterChip(
                        selected = filter == k,
                        onClick = { filter = k },
                        label = { Text("${STATUS_LABELS[k] ?: "すべて"} $n") },
                    )
                }
            }
            val shown = rows.filter { filter == "all" || it.second == filter }
            if (snap != null && shown.isEmpty()) {
                Text("該当するネタはありません", Modifier.padding(24.dp), color = Color.Gray)
            }
            LazyColumn(
                Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 88.dp),
            ) {
                items(shown, key = { it.first.id }) { (t, status) ->
                    TopicCard(
                        topic = t,
                        categoryName = snap?.categories?.get(t.category) ?: t.category.ifBlank { "おまかせ" },
                        status = status,
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

    if (showAdd) {
        var theme by remember { mutableStateOf("") }
        var memo by remember { mutableStateOf("") }
        var category by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAdd = false },
            title = { Text("ネタを追加") },
            text = {
                Column {
                    OutlinedTextField(
                        value = theme, onValueChange = { theme = it },
                        label = { Text("テーマ（必須）") }, modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    Text("カテゴリー", style = MaterialTheme.typography.labelMedium)
                    Row(
                        Modifier.horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        FilterChip(selected = category == "", onClick = { category = "" }, label = { Text("おまかせ") })
                        snapshot?.categories?.forEach { (id, name) ->
                            FilterChip(selected = category == id, onClick = { category = id }, label = { Text(name) })
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = memo, onValueChange = { memo = it },
                        label = { Text("メモ（切り口・希望など、任意）") }, modifier = Modifier.fillMaxWidth(), minLines = 2,
                    )
                    Text(
                        "追加したネタは、次の投稿のときに最優先で記事になります（1日8記事の上限内）。",
                        style = MaterialTheme.typography.bodySmall, color = Color.Gray, modifier = Modifier.padding(top = 6.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(enabled = theme.isNotBlank(), onClick = {
                    showAdd = false
                    scope.launch {
                        try {
                            withContext(Dispatchers.IO) { GitHubRepo(token).addRequest(theme, category, memo) }
                            snackbar.showSnackbar("追加しました。次の投稿で取り込まれます")
                            filter = "requested"
                            refresh()
                        } catch (e: Exception) {
                            snackbar.showSnackbar(e.message ?: "追加に失敗しました")
                        }
                    }
                }) { Text("追加") }
            },
            dismissButton = { TextButton(onClick = { showAdd = false }) { Text("キャンセル") } },
        )
    }

    if (showSettings) {
        var input by remember { mutableStateOf(token) }
        AlertDialog(
            onDismissRequest = { showSettings = false },
            title = { Text("GitHub トークン") },
            text = {
                Column {
                    Text("ネタの追加・削除に使います（閲覧だけならトークンなしで使えます）。" +
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

/** Queue topics plus not-yet-ingested app requests, newest first, each with the status to show. */
private fun allRows(snap: Snapshot): List<Pair<Topic, String>> {
    val queued = snap.topics.map { t ->
        t to (if (t.id in snap.skipped && t.status in setOf("approved", "hold", "failed")) "deleted" else t.status)
    }
    val requested = snap.requests.map { r ->
        Topic(
            id = "request:" + r.file, status = "requested", category = r.category, theme = r.theme, angle = r.memo,
            articleType = "", keywords = emptyList(), score = 0, sourceOfIdea = "user",
            created = r.requestedAt.take(10), slug = null,
        ) to "requested"
    }
    return (requested + queued).sortedWith(compareByDescending<Pair<Topic, String>> { it.first.created }.thenBy { it.first.id })
}

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
                val parts = listOfNotNull(
                    TYPE_LABELS[topic.articleType] ?: topic.articleType.ifBlank { null },
                    if (topic.score > 0 && status != "requested") "${topic.score}点" else null,
                    STATUS_LABELS[status] ?: status,
                )
                Text(
                    parts.joinToString("・"),
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
            val meta = if (status == "requested") listOf("アプリから追加", topic.created)
            else listOfNotNull(topic.id, topic.created, if (topic.sourceOfIdea == "user") "持ち込み" else null, topic.slug)
            Text(
                meta.filter { it.isNotBlank() }.joinToString("・"),
                style = MaterialTheme.typography.labelSmall,
                color = Color.Gray,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}
