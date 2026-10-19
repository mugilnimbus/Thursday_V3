package app.thursday

import app.thursday.domain.AgentChoices
import app.thursday.domain.AgentForm
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentFormTest {
    private val saved = AgentForm(provider = "lmstudio", baseUrl = "http://127.0.0.1:1234", model = "google/gemma", contextLength = "32768", flashAttention = "on")

    @Test
    fun switchingToTheBuiltInLlamaCppSendsNoAddressAndNoModel() {
        val local = AgentChoices.switchProvider(saved, saved, emptyMap(), "llamacpp").copy(modelsDir = "D:\\models")
        assertEquals(listOf("", ""), listOf(local.baseUrl, local.model))
        assertEquals(mapOf("provider" to "llamacpp", "models_dir" to "D:\\models"), AgentChoices.changes(saved, local))
        val back = AgentChoices.switchProvider(local, local, emptyMap(), "lmstudio")
        assertEquals("the address it starts with is sent", "http://localhost:1234", AgentChoices.changes(local, back)["base_url"])
    }

    @Test
    fun `only what changed is sent, with Default as null`() {
        assertEquals(emptyMap<String, Any?>(), AgentChoices.changes(saved, saved))
        val after = saved.copy(model = " google/other ", contextLength = "", flashAttention = "off", temperature = "0.7", reasoning = "low", compactAtTokens = "65536")
        assertEquals(
            mapOf(
                "model" to "google/other",
                "load" to mapOf("context_length" to null, "flash_attention" to false),
                "inference" to mapOf("temperature" to 0.7, "reasoning" to "low"),
                "compact_at_tokens" to 65536,
            ),
            AgentChoices.changes(saved, after),
        )
        val cleared = AgentChoices.changes(saved.copy(reasoning = "low", modelsDir = "D:\\m", gpu = "1"), saved)
        assertEquals(mapOf("inference" to mapOf("reasoning" to null), "models_dir" to null, "gpu" to null), cleared)
    }

    @Test
    fun `each provider lists the values it accepts with its default named first`() {
        assertEquals("" to "8,192 tokens (default)", AgentChoices.choices("context_length", "llamacpp", "").first())
        assertEquals("0.8 (default)", AgentChoices.choices("temperature", "llamacpp", "").first().second)
        assertEquals("1 (default)", AgentChoices.choices("temperature", "openai_compatible", "").first().second)
        assertEquals("LM Studio's (default)", AgentChoices.choices("context_length", "lmstudio", "").first().second)
        assertEquals(listOf("default", "off", "on"), AgentChoices.choices("reasoning", "llamacpp", "default").map { it.first })
        assertTrue(AgentChoices.choices("reasoning", "openai_compatible", "default").any { it.first == "xhigh" })
        assertTrue(AgentChoices.choices("temperature", "llamacpp", "").map { it.first }.containsAll(listOf("0", "0.7", "1", "2")))
    }

    @Test
    fun `a context longer than the model allows is not offered and an unusual saved value stays`() {
        val sizes = AgentChoices.choices("context_length", "lmstudio", "", 131072).map { it.first }
        assertTrue("131072" in sizes)
        assertFalse("262144" in sizes)
        assertEquals("32000" to "32000 (saved)", AgentChoices.choices("context_length", "lmstudio", "32000").last())
    }

    @Test
    fun `the context limit moves in steps of 1024 tokens`() {
        assertEquals("8192", AgentChoices.stepTokens("", up = true))
        assertEquals("", AgentChoices.stepTokens("", up = false))
        assertEquals("9216", AgentChoices.stepTokens("8192", up = true))
        assertEquals("4096", AgentChoices.stepTokens("5000", up = false))
        assertEquals("5120", AgentChoices.stepTokens("5000", up = true))
        assertEquals("", AgentChoices.stepTokens("1024", up = false))
        assertNull(AgentChoices.validate(saved.copy(compactAtTokens = "65536")))
        assertTrue(AgentChoices.validate(saved.copy(compactAtTokens = "5000"))!!.contains("multiple of 1024"))
        assertEquals("28672", AgentChoices.contextDefault("main", "lmstudio", 32768))
        assertEquals("no limit", AgentChoices.contextDefault("main", "openai_compatible", null))
        assertEquals("the last 60 messages", AgentChoices.contextDefault("voice", "lmstudio", 32768))
    }

    @Test
    fun `the built-in llama cpp needs no endpoint or model name`() {
        assertNull(AgentChoices.validate(AgentForm(provider = "llamacpp")))
        assertTrue(AgentChoices.validate(AgentForm(provider = "openai_compatible", baseUrl = "ftp://x", model = "m"))!!.contains("http"))
        assertTrue(AgentChoices.validate(saved.copy(model = " "))!!.contains("model"))
        assertFalse(AgentChoices.kind("llamacpp").endpoint)
        assertTrue(AgentChoices.kind("llamacpp").folders)
    }

    @Test
    fun `llama cpp can use every card, one card, some layers, or a chosen split`() {
        assertEquals("All cards (default)", AgentChoices.choices("gpu", "llamacpp", "").first().second)
        assertEquals(listOf("", "all", "8", "16", "24", "32", "48", "64", "0"), AgentChoices.choices("gpu_layers", "llamacpp", "").map { it.first })
        assertEquals("By free memory (default)", AgentChoices.choices("gpu_split", "llamacpp", "").first().second)
        val local = AgentForm(provider = "llamacpp")
        assertEquals(mapOf("load" to mapOf("gpu_layers" to "24", "gpu_split" to "3,1")), AgentChoices.changes(local, local.copy(gpuLayers = "24", gpuSplit = "3,1")))
        assertEquals(mapOf("load" to mapOf("gpu_layers" to null, "gpu_split" to null)), AgentChoices.changes(local.copy(gpuLayers = "all", gpuSplit = "1,1"), local))
    }

    @Test
    fun `an idle model is unloaded after a chosen time, with 0 for never`() {
        assertEquals("5", saved.idleUnloadMinutes)
        assertEquals(listOf("0", "1", "2", "5", "10", "15", "30", "60"), AgentChoices.choices("idle_unload_minutes", "lmstudio", "5").map { it.first })
        assertEquals("Never", AgentChoices.choices("idle_unload_minutes", "lmstudio", "5").first().second)
        assertEquals("7" to "7 minutes (saved)", AgentChoices.choices("idle_unload_minutes", "lmstudio", "7").last())
        assertEquals(mapOf("idle_unload_minutes" to 0.0), AgentChoices.changes(saved, saved.copy(idleUnloadMinutes = "0")))
        assertEquals(mapOf("idle_unload_minutes" to 30.0), AgentChoices.changes(saved, saved.copy(idleUnloadMinutes = "30")))
    }

    @Test
    fun `switching provider never carries a model or address to a provider it means nothing to`() {
        val lm = AgentForm(provider = "lmstudio", baseUrl = "http://127.0.0.1:2124", model = "google/gemma-4-12b-qat")
        val remembered = mapOf("openai_compatible" to ("big" to "https://api.example.com"))
        val local = AgentChoices.switchProvider(lm, lm, remembered, "llamacpp")
        assertEquals(listOf("llamacpp", "", ""), listOf(local.provider, local.model, local.baseUrl))
        assertNull(AgentChoices.validate(local, lm))
        val cloud = AgentChoices.switchProvider(local, lm, remembered, "openai_compatible")
        assertEquals("big" to "https://api.example.com", cloud.model to cloud.baseUrl)
        assertEquals(lm, AgentChoices.switchProvider(cloud, lm, remembered, "lmstudio"))

        val saved = AgentForm(provider = "llamacpp", model = "a.gguf")
        val studio = AgentChoices.switchProvider(saved, saved, emptyMap(), "lmstudio")
        assertEquals("http://localhost:1234", studio.baseUrl)
        assertNull("the list is not this provider's yet, so no model is demanded", AgentChoices.validate(studio, saved))
        assertTrue(AgentChoices.validate(studio)!!.contains("model"))
    }

    @Test
    fun `the only model there is gets chosen when nothing valid is chosen`() {
        val local = AgentForm(provider = "llamacpp", model = "google/gemma-4-12b-qat")
        assertEquals("gemma-12b-Q4.gguf", AgentChoices.onlyChoice(local, listOf("gemma-12b-Q4.gguf")))
        assertNull(AgentChoices.onlyChoice(local, listOf("a.gguf", "b.gguf")))
        assertNull(AgentChoices.onlyChoice(local.copy(model = "a.gguf"), listOf("a.gguf")))
        assertNull(AgentChoices.onlyChoice(saved, listOf("other/model")))
        assertEquals("other/model", AgentChoices.onlyChoice(saved.copy(model = ""), listOf("other/model")))
    }

    @Test
    fun `one card can be filled first, and the real cards are named`() {
        val cards = listOf(0 to "NVIDIA GeForce RTX 3080 Ti", 1 to "NVIDIA GeForce RTX 3080 Ti")
        assertEquals(
            listOf("" to "Spread over cards (default)", "0" to "Fill card 0 (RTX 3080 Ti) first", "1" to "Fill card 1 (RTX 3080 Ti) first"),
            AgentChoices.choices("gpu_priority", "llamacpp", "", cards = cards),
        )
        assertEquals("Only card 1 (RTX 3080 Ti)", AgentChoices.choices("gpu", "llamacpp", "", cards = cards).last().second)
        assertEquals(5, AgentChoices.choices("gpu_priority", "llamacpp", "").size)
        val local = AgentForm(provider = "llamacpp")
        assertEquals(mapOf("load" to mapOf("gpu_priority" to "1")), AgentChoices.changes(local, local.copy(gpuPriority = "1")))
        assertEquals(mapOf("load" to mapOf("gpu_priority" to null)), AgentChoices.changes(local.copy(gpuPriority = "1"), local))
    }
}
