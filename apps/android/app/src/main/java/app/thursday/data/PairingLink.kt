package app.thursday.data

import java.net.URI
import java.net.URLDecoder

/**
 * The pairing link from the dashboard (`thursday://pair?url=<address>&code=<code>`), or an address and code
 * typed by hand. Only HTTPS addresses are accepted, plus http://127.0.0.1 in debug builds (USB with adb reverse).
 * Pure Kotlin so it is unit tested.
 */
data class PairingLink(val baseUrl: String, val code: String) {
    companion object {
        private val CODE = Regex("^[A-Z0-9]{8}$")

        fun parse(text: String, allowLocalHttp: Boolean): PairingLink? {
            val uri = runCatching { URI(text.trim()) }.getOrNull() ?: return null
            if (uri.scheme != "thursday" || uri.host != "pair") return null
            val params = (uri.rawQuery ?: "").split("&").mapNotNull {
                val (k, v) = it.split("=", limit = 2).takeIf { p -> p.size == 2 } ?: return@mapNotNull null
                k to URLDecoder.decode(v, "UTF-8")
            }.toMap()
            return of(params["url"] ?: return null, params["code"] ?: return null, allowLocalHttp)
        }

        fun of(address: String, code: String, allowLocalHttp: Boolean): PairingLink? {
            val url = normalizeAddress(address, allowLocalHttp) ?: return null
            val clean = code.uppercase().filter { it.isLetterOrDigit() }
            return if (CODE.matches(clean)) PairingLink(url, clean) else null
        }

        /** `https://host[:port]` without a path, or null when the address is not allowed. */
        fun normalizeAddress(address: String, allowLocalHttp: Boolean): String? {
            val raw = address.trim().let { if ("://" in it) it else "https://$it" }
            val uri = runCatching { URI(raw) }.getOrNull() ?: return null
            val host = uri.host ?: return null
            val port = if (uri.port > 0) ":${uri.port}" else ""
            return when {
                uri.scheme == "https" && uri.userInfo == null -> "https://$host$port"
                allowLocalHttp && uri.scheme == "http" && host == "127.0.0.1" -> "http://$host$port"
                else -> null
            }
        }
    }
}
