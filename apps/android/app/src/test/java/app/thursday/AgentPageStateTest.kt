package app.thursday

import app.thursday.data.ApiException
import app.thursday.data.LlmSettings
import app.thursday.data.ModelEntry
import app.thursday.data.ModelListing
import app.thursday.domain.AgentForm
import app.thursday.ui.settings.AgentPageState
import app.thursday.ui.settings.AgentSettingsApi
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The rules of the agent settings page, run against a stand-in for the PC. */
class AgentPageStateTest {
    /** A PC that holds one agent's settings, applies changes the way the gateway does, and writes down every call. */
    private class FakePc(var form: AgentForm, var models: List<String> = listOf("gemma", "qwen")) : AgentSettingsApi {
        val calls = mutableListOf<String>()
        var loaded = false
        var keySet = false
        var fail: String? = null // the call that fails next, by name
        var listingError: String? = null

        private fun now() = LlmSettings(
            form, apiKeySet = keySet, sendsOffPc = false, supportsLifecycle = true, loadedContext = if (loaded) 8192 else null,
            loaded = loaded, reachable = true, installed = true, hearsAudio = false,
        )

        private fun step(name: String) {
            calls += name
            if (fail == name.substringBefore(' ')) {
                fail = null
                throw ApiException(503, "error", "The PC could not $name.")
            }
        }

        override suspend fun settings(agent: String): LlmSettings {
            step("settings")
            return now()
        }

        override suspend fun models(agent: String): ModelListing {
            step("models")
            listingError?.let { throw ApiException(502, "error", it) }
            return ModelListing(models.map { ModelEntry(it, loaded = false, maxContext = 32768, sizeBytes = null, projector = null) }, null)
        }

        override suspend fun change(agent: String, changes: Map<String, Any?>) {
            step("change $changes")
            (changes["model"] as? String)?.let { form = form.copy(model = it) }
            (changes["provider"] as? String)?.let { form = form.copy(provider = it) }
            (changes["base_url"] as? String)?.let { form = form.copy(baseUrl = it) }
            @Suppress("UNCHECKED_CAST")
            (changes["inference"] as? Map<String, Any?>)?.get("temperature")?.let { form = form.copy(temperature = it.toString().removeSuffix(".0")) }
        }

        override suspend fun setKey(agent: String, key: String): LlmSettings {
            step("key ${if (key.isEmpty()) "removed" else "stored"}") // the key itself is never written down
            keySet = key.isNotEmpty()
            return now()
        }

        override suspend fun model(agent: String, action: String): LlmSettings {
            step(action)
            loaded = action != "unload"
            return now()
        }
    }

    private val saved = AgentForm(provider = "lmstudio", baseUrl = "http://localhost:1234", model = "gemma")
    private val prompts = mutableListOf<String>()
    private var allow = true

    private fun page(pc: FakePc) = AgentPageState("main", "Main agent", pc) { prompt ->
        prompts += prompt
        allow
    }

    @Test
    fun openingShowsWhatThePcHoldsAndTheModelsItOffers() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        assertNull("nothing to draw before the PC answers", page.settings)
        page.open()
        assertEquals(saved, page.form)
        assertEquals(listOf("gemma", "qwen"), page.listing.models.map { it.key })
        assertFalse(page.dirty)
        assertFalse(page.canSave)
        assertTrue(page.canLoad)
        assertEquals(listOf("settings", "models"), pc.calls)
    }

    @Test
    fun aPcThatCannotBeReachedIsSaidOnThePage() = runBlocking<Unit> {
        val pc = FakePc(saved).apply { fail = "settings" }
        val page = page(pc)
        page.open()
        assertNull(page.settings)
        assertEquals("The PC could not settings.", page.error)
    }

    @Test
    fun savingSendsOnlyWhatChangedAndThenShowsWhatThePcHolds() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.form = page.form.copy(temperature = "0.7")
        assertTrue(page.dirty)
        assertTrue(page.canSave)
        pc.calls.clear()
        page.save()
        assertEquals(listOf("Change the Main agent settings"), prompts)
        assertEquals(listOf("change {inference={temperature=0.7}}", "settings", "models"), pc.calls)
        assertEquals("0.7", page.saved.temperature)
        assertFalse("what is on the page is what is saved", page.dirty)
        assertEquals("", page.busy)
        assertNull(page.error)
    }

    @Test
    fun nothingIsSentWhenTheFingerprintPromptIsDeclined() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.form = page.form.copy(model = "qwen")
        pc.calls.clear()
        allow = false
        page.save()
        page.load()
        page.removeKey()
        assertEquals(emptyList<String>(), pc.calls)
        assertEquals(3, prompts.size)
        assertEquals("the edit is still on the page", "qwen", page.form.model)
        assertTrue(page.dirty)
    }

    @Test
    fun aFailedSaveSaysWhyAndKeepsTheEdit() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.form = page.form.copy(model = "qwen")
        pc.fail = "change"
        page.save()
        assertTrue(page.error!!.startsWith("The PC could not change"))
        assertEquals("qwen", page.form.model)
        assertEquals("gemma", page.saved.model)
        assertEquals("the buttons work again", "", page.busy)
        assertTrue(page.canSave)
        page.save()
        assertNull("a later success clears the message", page.error)
        assertEquals("qwen", page.saved.model)
    }

    @Test
    fun aTypedKeyIsStoredWithSaveAndThenForgottenByThePhone() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.newKey = "  sk-test-key  "
        assertTrue("a typed key alone is something to save", page.canSave)
        pc.calls.clear()
        page.save()
        assertEquals(listOf("key stored", "settings", "models"), pc.calls)
        assertEquals("", page.newKey)
        assertTrue(page.settings!!.apiKeySet)
        page.removeKey()
        assertFalse(page.settings!!.apiKeySet)
    }

    @Test
    fun aKeyIsNotStoredWhileTheProviderIsChangingBecauseEachProviderHasItsOwn() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.newKey = "sk-test-key"
        page.switchProvider("openai_compatible")
        assertEquals("the other provider's model and address are not carried over", "" to "", page.form.model to page.form.baseUrl)
        page.form = page.form.copy(baseUrl = "https://api.example.com/v1")
        assertTrue("the models on screen are the old provider's", page.listingStale)
        assertFalse(page.canLoad)
        assertNull("so no model can be demanded yet", page.problem)
        pc.calls.clear()
        page.save()
        assertTrue(pc.calls.none { it.startsWith("key") })
        assertEquals("sk-test-key", page.newKey)
        assertEquals("openai_compatible", page.saved.provider)
        assertFalse(page.listingStale)
    }

    @Test
    fun reloadSavesTheEditFirstSoTheNewParametersAreTheOnesLoaded() = runBlocking<Unit> {
        val pc = FakePc(saved)
        val page = page(pc)
        page.open()
        page.form = page.form.copy(model = "qwen")
        pc.calls.clear()
        page.reload()
        assertEquals(listOf("change {model=qwen}", "settings", "reload", "models"), pc.calls)
        assertTrue(page.settings!!.loaded)
        assertEquals("qwen", page.saved.model)
        page.unload()
        assertFalse(page.settings!!.loaded)
    }

    @Test
    fun theOnlyModelThereIsIsChosenAsAnUnsavedChange() = runBlocking<Unit> {
        val pc = FakePc(saved.copy(model = ""), models = listOf("gemma"))
        val page = page(pc)
        page.open()
        assertEquals("gemma", page.form.model)
        assertEquals("", page.saved.model)
        assertTrue(page.dirty)
    }

    @Test
    fun aModelListThatCannotBeReadIsSaidAndThePageStillWorks() = runBlocking<Unit> {
        val pc = FakePc(saved).apply { listingError = "LM Studio is not running." }
        val page = page(pc)
        page.open()
        assertEquals(saved, page.form)
        assertEquals("LM Studio is not running.", page.listing.error)
        assertTrue(page.listing.models.isEmpty())
        assertTrue("a name can still be typed and loaded", page.canLoad)
    }

    @Test
    fun aFolderOfFilesOnlyLoadsAModelThatIsInTheFolder() = runBlocking<Unit> {
        val pc = FakePc(AgentForm(provider = "llamacpp", model = "missing.gguf", modelsDir = "D:/models"), models = listOf("a.gguf", "b.gguf"))
        val page = page(pc)
        page.open()
        assertNull(page.chosen)
        assertFalse(page.canLoad)
        page.form = page.form.copy(model = "b.gguf")
        assertTrue(page.canLoad)
        assertEquals(32768, page.chosen?.maxContext)
        assertTrue("sizes above the model's limit are not offered", page.choices("context_length", "").none { it.first == "65536" })
        page.browsing = true
        page.chooseFolder("E:/other")
        assertFalse(page.browsing)
        assertTrue(page.listingStale)
    }
}
