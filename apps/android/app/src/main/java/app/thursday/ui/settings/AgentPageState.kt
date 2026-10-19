package app.thursday.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.thursday.data.LlmSettings
import app.thursday.data.ModelEntry
import app.thursday.data.ModelListing
import app.thursday.domain.AgentChoices
import app.thursday.domain.AgentForm
import app.thursday.domain.ProviderKind
import kotlinx.coroutines.CancellationException

/** What the agent page needs from the PC. The gateway client is behind it in the app; a test puts a fake there. */
interface AgentSettingsApi {
    suspend fun settings(agent: String): LlmSettings
    suspend fun models(agent: String): ModelListing

    /** Send the changed settings: a nested map shaped like the API's request, where null clears a value. */
    suspend fun change(agent: String, changes: Map<String, Any?>)

    /** Store the key for the agent's saved provider; an empty key removes it. */
    suspend fun setKey(agent: String, key: String): LlmSettings

    /** `action` is load, unload or reload. */
    suspend fun model(agent: String, action: String): LlmSettings
}

/**
 * Everything the agent page shows and does, apart from drawing it: the saved settings, the form being edited, the
 * list of models, and the actions (save, load, unload, reload, remove the key).
 *
 * The page draws this state and calls these functions and decides nothing itself, so the rules of the page are in
 * one place and are tested without a phone. Every action that changes the PC asks [confirm] first (the fingerprint
 * or lock-screen prompt) and does nothing when it is declined.
 */
class AgentPageState(
    val agent: String,
    private val title: String,
    private val api: AgentSettingsApi,
    private val confirm: suspend (String) -> Boolean,
) {
    /** What the PC holds. Null until it has answered. */
    var settings by mutableStateOf<LlmSettings?>(null)
        private set

    /** The form as edited on the phone. It differs from [settings] until Save. */
    var form by mutableStateOf(AgentForm())
    var listing by mutableStateOf(ModelListing(emptyList(), null))
        private set

    /** The model name is typed instead of picked from the list. */
    var typing by mutableStateOf(false)

    /** The PC's folders are open to choose the models folder. */
    var browsing by mutableStateOf(false)
    var newKey by mutableStateOf("")

    /** The action in progress ("save", "load", "unload", "reload", "key"), or empty. */
    var busy by mutableStateOf("")
        private set
    var error by mutableStateOf<String?>(null)
        private set

    val saved: AgentForm get() = settings?.form ?: AgentForm()
    val kind: ProviderKind get() = AgentChoices.kind(form.provider)

    /** The provider, address or folder was edited, so the model list on screen is not this provider's. */
    val listingStale: Boolean get() = AgentChoices.listingChanged(saved, form)
    val chosen: ModelEntry? get() = listing.models.firstOrNull { it.key == form.model }

    /** Why the form cannot be saved, or null. */
    val problem: String? get() = AgentChoices.validate(form, saved)

    /** A model this provider can load: for a folder of files it must be one of them; elsewhere any name will do. */
    val loadable: Boolean get() = form.model.isNotBlank() && (!kind.folders || chosen != null)

    /** A typed key is stored only when the provider itself is not changing: each provider has its own. */
    private val keyTyped: Boolean get() = newKey.isNotBlank() && form.provider == saved.provider
    val dirty: Boolean get() = settings != null && (form != saved || keyTyped)
    val canSave: Boolean get() = dirty && problem == null && busy.isEmpty()
    val canLoad: Boolean get() = busy.isEmpty() && loadable && !listingStale
    val canReload: Boolean get() = canLoad && problem == null

    /** The values a setting can take now, as (value, label). */
    fun choices(field: String, value: String): List<Pair<String, String>> =
        AgentChoices.choices(field, form.provider, value, if (field == "context_length") chosen?.maxContext else null, settings?.cards.orEmpty())

    fun switchProvider(next: String) {
        form = AgentChoices.switchProvider(form, saved, settings?.remembered.orEmpty(), next)
    }

    fun chooseFolder(path: String) {
        form = form.copy(modelsDir = path)
        browsing = false
    }

    /** Read what the PC holds and the models it offers. */
    suspend fun open() {
        try {
            take(api.settings(agent))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.message
        }
    }

    /** The models the saved settings offer. Listing never loads anything. */
    suspend fun listModels() {
        val found = try {
            api.models(agent)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ModelListing(emptyList(), e.message)
        }
        listing = found
        // With one model to choose from and nothing valid chosen, choose it: it shows as an unsaved change.
        if (settings != null && !listingStale) AgentChoices.onlyChoice(form, found.models.map { it.key })?.let { form = form.copy(model = it) }
    }

    suspend fun save() = act("save", "Change the $title settings") { store() }

    suspend fun load() = act("load", "Load the $title model") { api.model(agent, "load") }

    suspend fun unload() = act("unload", "Unload the $title model") { api.model(agent, "unload") }

    /** Reload applies the load parameters now, so what was edited is saved first. */
    suspend fun reload() = act("reload", "Reload the $title model") {
        store()
        api.model(agent, "reload")
    }

    suspend fun removeKey() = act("key", "Remove the $title API key") { api.setKey(agent, "") }

    private suspend fun act(label: String, prompt: String, block: suspend () -> LlmSettings) {
        if (busy.isNotEmpty() || !confirm(prompt)) return
        busy = label
        error = null
        val result = try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.message
            null
        } finally {
            busy = ""
        }
        if (result != null) take(result)
    }

    /** Send what changed, and the typed key, and read back what the PC now holds. */
    private suspend fun store(): LlmSettings {
        val before = saved
        val diff = AgentChoices.changes(before, form)
        if (diff.isNotEmpty()) api.change(agent, diff)
        val key = newKey.trim()
        if (key.isNotEmpty() && form.provider == before.provider) {
            api.setKey(agent, key)
            newKey = ""
        }
        return api.settings(agent)
    }

    private suspend fun take(fresh: LlmSettings) {
        settings = fresh
        form = fresh.form
        listModels()
    }
}
