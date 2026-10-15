package io.github.kingsworksub.topics

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val PLATFORM_LABELS = linkedMapOf(
    "github" to "GitHub Pages",
    "hatena" to "はてなブログ",
    "ameba" to "アメブロ",
    "note" to "note",
)

/** Lists already-published posts and lets the user edit each one's target platform set (PPP).
 * Saving drops a request file that scripts/platform_sync.py picks up on its own schedule — this
 * screen never talks to Hatena/Ameba/note directly, only to the GitHub Contents API, same as the
 * rest of this app. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlatformsScreen(token: String, onBack: () -> Unit) {
    var posts by remember { mutableStateOf<List<PublishedPost>?>(null) }
    var loading by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<PublishedPost?>(null) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    fun refresh() {
        if (loading) return
        loading = true
        scope.launch {
            try {
                posts = withContext(Dispatchers.IO) { GitHubRepo(token).loadPublishedPosts() }
            } catch (e: Exception) {
                snackbar.showSnackbar("読み込みに失敗しました: ${e.message}")
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) { refresh() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("公開済み記事") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, "戻る") }
                },
                actions = {
                    IconButton(onClick = { refresh() }) { Icon(Icons.Filled.Refresh, "更新") }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            val list = posts
            if (list != null && list.isEmpty()) {
                Text(
                    "公開済み記事がありません(post-platforms.json が未生成の可能性があります)",
                    Modifier.padding(24.dp), color = Color.Gray,
                )
            } else if (list != null) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp)) {
                    items(list, key = { it.slug }) { post ->
                        PublishedPostCard(post, onEdit = { editing = post })
                    }
                }
            }
        }
    }

    editing?.let { post ->
        var selected by remember(post.slug) { mutableStateOf(post.platforms.toSet()) }
        var confirmingClear by remember(post.slug) { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text(post.title, maxLines = 2) },
            text = {
                Column {
                    Text("投稿先プラットフォーム", style = MaterialTheme.typography.labelMedium)
                    PLATFORM_LABELS.forEach { (id, label) ->
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Checkbox(
                                checked = id in selected,
                                onCheckedChange = { checked ->
                                    selected = if (checked) selected + id else selected - id
                                    confirmingClear = false
                                },
                            )
                            Text(label)
                        }
                    }
                    if (selected.isEmpty()) {
                        Text(
                            "すべて外すと、この記事は全プラットフォームから削除されます。",
                            color = Color(0xFFB3261E), style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                    post.needsManualReview?.let {
                        Text(
                            "要確認: $it", color = Color(0xFFB3261E),
                            style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    if (selected.isEmpty() && !confirmingClear) {
                        confirmingClear = true
                        return@TextButton
                    }
                    val target = selected.toList()
                    editing = null
                    scope.launch {
                        try {
                            withContext(Dispatchers.IO) { GitHubRepo(token).requestPlatformChange(post.slug, target) }
                            snackbar.showSnackbar("変更をリクエストしました。反映まで時間がかかります")
                            refresh()
                        } catch (e: Exception) {
                            snackbar.showSnackbar(e.message ?: "リクエストに失敗しました")
                        }
                    }
                }) { Text(if (selected.isEmpty() && !confirmingClear) "全プラットフォームから削除する" else "変更を送信") }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("キャンセル") } },
        )
    }
}

@Composable
private fun PublishedPostCard(post: PublishedPost, onEdit: () -> Unit) {
    Card(onClick = onEdit, modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text(post.title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            Text(
                post.platforms.joinToString("・") { PLATFORM_LABELS[it] ?: it }.ifBlank { "(非公開)" },
                style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp),
            )
            post.needsManualReview?.let {
                Text(
                    "要確認: $it", color = Color(0xFFB3261E),
                    style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp),
                )
            }
            Text(post.slug, style = MaterialTheme.typography.labelSmall, color = Color.Gray,
                modifier = Modifier.padding(top = 4.dp))
        }
    }
}
