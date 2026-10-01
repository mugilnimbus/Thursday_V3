package app.thursday.ui.pair

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.thursday.BuildConfig
import app.thursday.MainActivity
import app.thursday.R
import app.thursday.data.ApiException
import app.thursday.data.PairingLink
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Field
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch

/** First run: pair with the PC by scanning the dashboard's code or typing its address and code. */
@Composable
fun PairScreen(activity: MainActivity) {
    val graph = activity.graph
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    // The name the owner gave the phone (for example "Pixel 9"), else the model code.
    var name by remember { mutableStateOf(android.provider.Settings.Global.getString(activity.contentResolver, "device_name") ?: Build.MODEL ?: "Phone") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var scanning by remember { mutableStateOf(false) }

    fun pair(link: PairingLink?) {
        if (link == null) {
            error = "Enter the address shown in the dashboard (https://…ts.net) and the 8-character code."
            return
        }
        busy = true
        error = null
        scope.launch {
            try {
                graph.paired(graph.api.claim(link, name.trim().ifEmpty { "Phone" }))
            } catch (e: ApiException) {
                error = when (e.status) {
                    422 -> "That code is wrong or has expired. Make a new one in the dashboard."
                    429 -> "Too many tries. Wait a minute, then try again."
                    else -> e.message
                }
            } finally {
                busy = false
            }
        }
    }

    val camera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) scanning = true else error = "Camera access was declined. Type the address and code instead."
    }

    if (scanning) {
        Box(Modifier.fillMaxSize()) {
            QrScanner(onCode = { text ->
                scanning = false
                val link = PairingLink.parse(text, BuildConfig.ALLOW_LOCAL_HTTP)
                if (link == null) error = "That QR code is not a Thursday pairing code." else {
                    address = link.baseUrl
                    code = link.code
                    pair(link)
                }
            }, modifier = Modifier.fillMaxSize())
            Column(Modifier.align(Alignment.BottomCenter).padding(Space.s5), horizontalAlignment = Alignment.CenterHorizontally) {
                Caption("Point the camera at the pairing code on your PC", color = p.text)
                Btn("Cancel", { scanning = false }, look = Look.NORMAL, modifier = Modifier.padding(top = Space.s3))
            }
        }
        return
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().imePadding().verticalScroll(rememberScrollState()).padding(Space.s4),
        verticalArrangement = Arrangement.spacedBy(Space.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Image(painterResource(R.drawable.logo), contentDescription = "Thursday", modifier = Modifier.padding(top = Space.s5).size(112.dp))
        Txt("Pair with your PC", size = Type.large, weight = FontWeight.SemiBold)
        Caption(
            "On the PC, open the Thursday dashboard, then Settings, Devices, and make a pairing code. The phone and the PC must both be on your Tailscale network.",
            color = p.muted,
        )
        Panel(Modifier.fillMaxWidth()) {
            Btn("Scan the code", {
                if (ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) scanning = true
                else camera.launch(Manifest.permission.CAMERA)
            }, look = Look.PRIMARY, modifier = Modifier.fillMaxWidth(), enabled = !busy)
            Caption("Or type what the dashboard shows:", color = p.muted)
            Field(address, { address = it }, label = "Address", placeholder = "https://your-pc.tailnet.ts.net", mono = true)
            Field(code, { code = it }, label = "Code", placeholder = "ABCD-EFGH", mono = true)
            Field(name, { name = it }, label = "Name for this phone")
            error?.let { Txt(it, color = p.danger, size = Type.caption) }
            Btn(if (busy) "Pairing…" else "Pair", { pair(PairingLink.of(address, code, BuildConfig.ALLOW_LOCAL_HTTP)) },
                modifier = Modifier.fillMaxWidth(), enabled = !busy && address.isNotBlank() && code.isNotBlank())
        }
        Caption("The code works once and expires after 5 minutes. This phone keeps its token in the Android Keystore.", color = p.muted)
        Box(Modifier.height(Space.s4).clip(RoundedCornerShape(Radius.sm)))
    }
}
