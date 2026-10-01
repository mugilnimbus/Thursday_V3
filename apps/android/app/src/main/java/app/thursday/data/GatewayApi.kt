package app.thursday.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiException(val status: Int, val code: String, message: String) : Exception(message) {
    val offline: Boolean get() = status == 0
    val unauthorized: Boolean get() = status == 401
}

/**
 * Typed calls to the gateway's proxy listener (reached through `tailscale serve`). Every call sends the
 * device token; nothing is logged. A 401 means this phone was revoked, reported through [onUnauthorized].
 */
class GatewayApi(
    private val pairing: () -> TokenStore.Pairing?,
    private val onUnauthorized: () -> Unit,
) {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .pingInterval(25, TimeUnit.SECONDS)
        .build()
    private val slow = client.newBuilder().readTimeout(15, TimeUnit.MINUTES).build() // model loads, backups

    /** Claim a pairing code. No token yet: the code is the credential. */
    suspend fun claim(link: PairingLink, deviceName: String): TokenStore.Pairing {
        val body = JSONObject().put("code", link.code).put("name", deviceName)
        val request = Request.Builder().url("${link.baseUrl}/v1/devices/claim").post(body.toString().toRequestBody(JSON)).build()
        val o = try {
            JSONObject(execute(client, request, authenticated = false))
        } catch (e: ApiException) {
            if (!e.offline) throw e
            val hint = if (link.baseUrl.startsWith("https://")) {
                "On the PC, Tailscale Serve must forward to Thursday: run `tailscale serve --bg http://127.0.0.1:8701`. Over a USB cable, use http://127.0.0.1:8701 instead."
            } else {
                "Over USB, the PC must forward the port: run `adb reverse tcp:8701 tcp:8701` and check that Thursday is running."
            }
            throw ApiException(0, "offline", "Cannot reach ${link.baseUrl}. $hint")
        }
        return TokenStore.Pairing(link.baseUrl, o.getString("device_id"), o.getString("token"))
    }

    suspend fun status() = Parse.status(obj("GET", "/v1/status"))
    suspend fun projects() = obj("GET", "/v1/projects").optJSONArray("projects").mapObjects(Parse::project)
    suspend fun createProject(name: String, folder: String) = Parse.project(obj("POST", "/v1/projects", JSONObject().put("name", name).put("folder", folder)))
    suspend fun folders(path: String): FolderListing {
        val o = obj("GET", "/v1/fs/folders?path=" + enc(path))
        return FolderListing(o.optString("path"), o.str("parent"), o.optJSONArray("folders").mapObjects { FolderRef(it.optString("name"), it.optString("path")) }, o.optString("home"))
    }
    suspend fun files(projectId: String, path: String, q: String?): List<FileEntry> =
        obj("GET", "/v1/projects/$projectId/files?path=" + enc(path) + (q?.takeIf { it.isNotBlank() }?.let { "&q=" + enc(it) } ?: ""))
            .optJSONArray("entries").mapObjects { FileEntry(it.optString("name"), it.optString("path"), it.optBoolean("is_dir"), if (it.isNull("size")) null else it.optLong("size")) }
    suspend fun file(projectId: String, path: String): FilePreview {
        val o = obj("GET", "/v1/projects/$projectId/file?path=" + enc(path))
        return FilePreview(o.optString("path"), o.optLong("size"), o.str("text"), o.optBoolean("truncated"), o.optBoolean("binary"))
    }
    private fun enc(value: String) = java.net.URLEncoder.encode(value, "UTF-8")

    suspend fun chats(projectId: String) = obj("GET", "/v1/projects/$projectId/chats").optJSONArray("chats").mapObjects(Parse::chat)
    suspend fun createChat(projectId: String) = Parse.chat(obj("POST", "/v1/projects/$projectId/chats", JSONObject()).put("last_activity", ""))
    suspend fun renameChat(chatId: String, title: String) = obj("PATCH", "/v1/chats/$chatId", JSONObject().put("title", title))
    suspend fun deleteChat(chatId: String) = obj("DELETE", "/v1/chats/$chatId")

    suspend fun messages(chatId: String, before: Long? = null): Pair<List<ChatMessage>, List<Pending>> {
        val o = obj("GET", "/v1/chats/$chatId/messages" + (before?.let { "?before=$it" } ?: ""))
        return o.optJSONArray("messages").mapObjects(Parse::message) to o.optJSONArray("pending").mapObjects(Parse::pending)
    }
    suspend fun send(chatId: String, clientMessageId: String, text: String) =
        obj("POST", "/v1/chats/$chatId/messages", JSONObject().put("client_message_id", clientMessageId).put("text", text))
    suspend fun timeline(chatId: String, after: Long) =
        obj("GET", "/v1/chats/$chatId/timeline?after=$after&limit=1000").optJSONArray("events").mapObjects {
            Parse.event(it.getLong("pos"), it.getJSONObject("event"))
        }

    suspend fun tasks(state: String, q: String?) =
        obj("GET", "/v1/tasks?state=$state" + (q?.takeIf { it.isNotBlank() }?.let { "&q=" + java.net.URLEncoder.encode(it, "UTF-8") } ?: ""))
            .optJSONArray("tasks").mapObjects(Parse::task)
    suspend fun task(taskId: String): Pair<TaskRow, List<app.thursday.domain.Event>> {
        val o = obj("GET", "/v1/tasks/$taskId")
        return Parse.task(o.getJSONObject("task")) to o.optJSONArray("trace").mapObjects { Parse.event(it.getLong("pos"), it.getJSONObject("event")) }
    }
    suspend fun control(taskId: String, action: String) = obj("POST", "/v1/tasks/$taskId/$action", JSONObject())

    suspend fun approvals() = obj("GET", "/v1/approvals").optJSONArray("approvals").mapObjects(Parse::approval)
    suspend fun answer(approvalId: String, decision: String) = obj("POST", "/v1/approvals/$approvalId", JSONObject().put("decision", decision))

    suspend fun tools() = Parse.tools(obj("GET", "/v1/tools"))
    suspend fun revokeRule(chatId: String, tool: String) = obj("DELETE", "/v1/chats/$chatId/allow-rules/${java.net.URLEncoder.encode(tool, "UTF-8")}")
    suspend fun monitor(range: String): MonitorData {
        val o = obj("GET", "/v1/monitor?range=$range")
        fun num(c: JSONObject, key: String) = if (c.isNull(key)) null else c.optDouble(key)
        val calls = o.optJSONArray("llm_calls").mapObjects {
            LlmCall(it.optString("ts"), it.optString("agent"), num(it, "tokens_per_second"), num(it, "ttft_seconds"), num(it, "input_tokens")?.toInt(), num(it, "context_length")?.toInt())
        }
        return MonitorData(o.optJSONObject("latest")?.let(Parse::sample), o.optJSONArray("history").mapObjects(Parse::sample), calls)
    }

    suspend fun llm(agent: String) = Parse.llm(obj("GET", "/v1/agents/$agent/llm"))
    suspend fun putLlm(agent: String, changes: JSONObject) = obj("PUT", "/v1/agents/$agent/llm", changes)
    suspend fun reloadKeys(agent: String) = Parse.llm(obj("POST", "/v1/agents/$agent/llm/reload-keys", JSONObject()))
    suspend fun model(agent: String, action: String) = Parse.llm(obj("POST", "/v1/agents/$agent/model/$action", null, slow))
    suspend fun prompt(agent: String) = obj("GET", "/v1/agents/$agent/prompt")
    suspend fun savePrompt(agent: String, text: String) = obj("PUT", "/v1/agents/$agent/prompt", JSONObject().put("text", text))
    suspend fun general() = obj("GET", "/v1/settings/general")
    suspend fun saveGeneral(changes: JSONObject) = obj("PUT", "/v1/settings/general", changes)
    suspend fun backupSettings() = obj("GET", "/v1/settings/backup")
    suspend fun backupNow() = obj("POST", "/v1/backup", JSONObject(), slow)
    suspend fun speechAvailable(): Boolean = obj("GET", "/v1/speech").optBoolean("available")

    /** Send a recorded clip; returns the text heard. */
    suspend fun transcribe(audio: ByteArray, mime: String): String {
        val p = pairing() ?: throw ApiException(401, "unpaired", "This phone is not paired.")
        val request = Request.Builder().url(p.baseUrl + "/v1/speech/transcribe").header("Authorization", "Bearer ${p.token}")
            .post(audio.toRequestBody(mime.toMediaType())).build()
        return JSONObject(String(bytes(slow, request), Charsets.UTF_8)).optString("text")
    }

    /** Returns WAV audio of the text read aloud. */
    suspend fun speak(text: String): ByteArray {
        val p = pairing() ?: throw ApiException(401, "unpaired", "This phone is not paired.")
        val request = Request.Builder().url(p.baseUrl + "/v1/speech/speak").header("Authorization", "Bearer ${p.token}")
            .post(JSONObject().put("text", text).toString().toRequestBody(JSON)).build()
        return bytes(slow, request)
    }

    suspend fun devices() = obj("GET", "/v1/devices").optJSONArray("devices").mapObjects(Parse::device)
    suspend fun revokeDevice(deviceId: String) = obj("DELETE", "/v1/devices/$deviceId")

    fun streamRequest(after: Long): Request? {
        val p = pairing() ?: return null
        val http = "${p.baseUrl}/v1/stream".toHttpUrl().newBuilder().addQueryParameter("after", after.toString()).build()
        return Request.Builder().url(http).header("Authorization", "Bearer ${p.token}").build()
    }

    fun metricsRequest(): Request? {
        val p = pairing() ?: return null
        return Request.Builder().url("${p.baseUrl}/v1/metrics/stream").header("Authorization", "Bearer ${p.token}").build()
    }

    private suspend fun obj(method: String, path: String, body: JSONObject? = null, http: OkHttpClient = client): JSONObject {
        val p = pairing() ?: throw ApiException(401, "unpaired", "This phone is not paired.")
        val request = Request.Builder()
            .url(p.baseUrl + path)
            .header("Authorization", "Bearer ${p.token}")
            .method(method, if (method == "GET" || method == "DELETE") null else (body ?: JSONObject()).toString().toRequestBody(JSON))
            .build()
        val text = execute(http, request, authenticated = true)
        return if (text.isBlank()) JSONObject() else runCatching { JSONObject(text) }.getOrElse { JSONObject().put("items", JSONArray(text)) }
    }

    private suspend fun bytes(http: OkHttpClient, request: Request): ByteArray = withContext(Dispatchers.IO) {
        val response = try {
            http.newCall(request).await()
        } catch (e: IOException) {
            throw ApiException(0, "offline", "Cannot reach your PC. Check that Tailscale is on.")
        }
        response.use {
            val body = it.body?.bytes() ?: ByteArray(0)
            if (it.isSuccessful) return@withContext body
            val problem = runCatching { JSONObject(String(body, Charsets.UTF_8)) }.getOrNull()
            if (it.code == 401) withContext(Dispatchers.Main) { onUnauthorized() }
            throw ApiException(it.code, "speech", problem?.optString("detail").orEmpty().ifEmpty { "Speech request failed (${it.code})." })
        }
    }

    /** Runs on the IO dispatcher: Android forbids network reads (including the response body) on the main thread. */
    private suspend fun execute(http: OkHttpClient, request: Request, authenticated: Boolean): String = withContext(Dispatchers.IO) {
        val response = try {
            http.newCall(request).await()
        } catch (e: IOException) {
            throw ApiException(0, "offline", "Cannot reach your PC. Check that Tailscale is on.")
        }
        response.use {
            val text = it.body?.string().orEmpty()
            if (it.isSuccessful) return@withContext text
            val problem = runCatching { JSONObject(text) }.getOrNull()
            if (it.code == 401 && authenticated) withContext(Dispatchers.Main) { onUnauthorized() }
            throw ApiException(
                it.code,
                problem?.optString("code").orEmpty().ifEmpty { "error" },
                problem?.optString("detail").orEmpty().ifEmpty { problem?.optString("title").orEmpty() }.ifEmpty { "Request failed (${it.code})." },
            )
        }
    }

    private companion object {
        val JSON = "application/json".toMediaType()
    }
}

suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    cont.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) = cont.resumeWithException(e)
        override fun onResponse(call: Call, response: Response) = cont.resume(response)
    })
}
