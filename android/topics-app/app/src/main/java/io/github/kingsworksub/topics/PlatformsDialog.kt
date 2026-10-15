package io.github.kingsworksub.topics

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

val PLATFORM_LABELS = linkedMapOf(
    "github" to "GitHub Pages",
    "hatena" to "はてなブログ",
    "ameba" to "アメブロ",
    "note" to "note",
)

/** Edits the target platform set (PPP) of one already-published post. Opened from a tap on its
 * card in the main list (status == "published" only). Saving drops a request file that
 * scripts/platform_sync.py reconciles on its own schedule -- this dialog only talks to the
 * GitHub Contents API, same as the rest of this app. */
@Composable
fun PlatformsEditDialog(
    title: String,
    current: List<String>,
    needsManualReview: String?,
    onDismiss: () -> Unit,
    onSave: (List<String>) -> Unit,
) {
    var selected by remember(title) { mutableStateOf(current.toSet()) }
    var confirmingClear by remember(title) { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title, maxLines = 2) },
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
                needsManualReview?.let {
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
                } else {
                    onSave(selected.toList())
                }
            }) { Text(if (selected.isEmpty() && !confirmingClear) "全プラットフォームから削除する" else "変更を送信") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}
