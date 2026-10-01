package app.thursday.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The pairing: the PC's address and this phone's device token.
 *
 * The token is encrypted with an AES-GCM key that lives in the Android Keystore and never leaves it;
 * only the ciphertext is stored in app preferences (excluded from backups). Nothing here is logged.
 */
class TokenStore(context: Context) {
    data class Pairing(val baseUrl: String, val deviceId: String, val token: String)

    private val prefs = context.getSharedPreferences("pairing", Context.MODE_PRIVATE)

    fun load(): Pairing? {
        val url = prefs.getString(KEY_URL, null) ?: return null
        val device = prefs.getString(KEY_DEVICE, null) ?: return null
        val sealed = prefs.getString(KEY_TOKEN, null) ?: return null
        val token = runCatching { open(sealed) }.getOrNull() ?: return null // key gone (for example after a reset)
        return Pairing(url, device, token)
    }

    fun save(pairing: Pairing) {
        prefs.edit()
            .putString(KEY_URL, pairing.baseUrl)
            .putString(KEY_DEVICE, pairing.deviceId)
            .putString(KEY_TOKEN, seal(pairing.token))
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
        runCatching { keyStore().deleteEntry(ALIAS) }
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun key(): SecretKey {
        (keyStore().getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun seal(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(sealed, Base64.NO_WRAP)
    }

    private fun open(encoded: String): String {
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_BYTES))
        return String(cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES), Charsets.UTF_8)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "thursday.device-token"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val KEY_URL = "base_url"
        const val KEY_DEVICE = "device_id"
        const val KEY_TOKEN = "token"
    }
}
