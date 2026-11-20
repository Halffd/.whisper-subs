package com.halffd.whispersubs

import android.content.Intent
import android.content.res.Configuration
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.LocalLibraryRepository
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.ui.channels.ChannelsScreen
import com.halffd.whispersubs.ui.channels.ChannelVideosScreen
import com.halffd.whispersubs.ui.connect.ConnectScreen
import com.halffd.whispersubs.ui.home.HomeScreen
import com.halffd.whispersubs.ui.home.VideosScreen
import com.halffd.whispersubs.ui.history.HistoryScreen
import com.halffd.whispersubs.ui.youtube.YouTubeScreen
import com.halffd.whispersubs.ui.connect.ConnectScreen
import com.halffd.whispersubs.ui.library.LibraryScreen
import com.halffd.whispersubs.ui.live.LiveScreen
import com.halffd.whispersubs.ui.local.LocalPlayerScreen
import com.halffd.whispersubs.ui.local.LocalScreen
import com.halffd.whispersubs.ui.player.PipState
import com.halffd.whispersubs.ui.player.PlayerScreen
import com.halffd.whispersubs.ui.search.SearchScreen
import com.halffd.whispersubs.ui.settings.SettingsScreen
import com.halffd.whispersubs.ui.theme.WhisperSubsTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var serverConfig: ServerConfig

    @Inject
    lateinit var apiClient: ApiClient

    @Inject
    lateinit var localLibraryRepository: LocalLibraryRepository

    private var isConnected by mutableStateOf(false)

    /** Pending route from an onNewIntent deep link; consumed by AppNavHost. */
    private val deepLinkRoute = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        isConnected = serverConfig.isConfigured()
        val deepLink = intent?.let { parseDeepLink(it) }
        setContent {
            WhisperSubsTheme {
                Surface {
                    AppNavHost(
                        startDestination = if (isConnected) "home" else "connect",
                        initialDeepLink = deepLink,
                        onConnected = { isConnected = true },
                        serverConfig = serverConfig,
                    )
                }
            }
        }
    }

    /**
     * Handles `whispersubs://…` deep links (home-screen widget search, API
     * /connect QR, URL input) sent to this already-running activity
     * (launchMode singleTop). No intent-filter existed for the scheme, so
     * the widget's tap fell through to the launcher start instead.
     */
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        val route = parseDeepLink(intent)
        if (route != null) {
            deepLinkRoute.value = route
        }
    }

    /** Maps a whispersubs:// URI to a navigation route, or null. */
    private fun parseDeepLink(intent: Intent): String? {
        // "Share a link with WhisperSubs" from any app: resolve the shared
        // media URL in the search screen instead of requiring a paste.
        if (intent.action == Intent.ACTION_SEND) {
            val shared = intent.getStringExtra(Intent.EXTRA_TEXT)
            val url = shared?.trim()?.takeIf { it.startsWith("http") }
                ?: return null
            return if (MediaLinks.isMediaUrl(url)) {
                "search?query=${Uri.encode(url)}"
            } else {
                null
            }
        }
        val uri = intent.data ?: return null
        if (uri.scheme != "whispersubs") return null
        return when (uri.host) {
            "search" -> "search?query=${Uri.encode(uri.getQueryParameter("query") ?: "")}"
            "history" -> "history"
            "youtube" -> "youtube"
            "settings" -> "settings"
            "connect" -> "connect"
            "home" -> "home"
            "live" -> "live"
            "local" -> "local"
            "library" -> "library"
            "channels" -> "channels"
            else -> null
        }
    }

    override fun onPictureInPictureModeChanged(isInPiP: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(isInPiP, newConfig)
        PipState.isInPip = isInPiP
    }
}

@androidx.compose.runtime.Composable
private fun AppNavHost(
    startDestination: String,
    initialDeepLink: String? = null,
    onConnected: () -> Unit,
    serverConfig: ServerConfig,
) {
    val navController: NavHostController = rememberNavController()
    val context = LocalContext.current

    // A deep link can arrive before (intent) or after (onNewIntent, kept on
    // the activity as state) the NavHost composes. Both paths land here:
    // the first sets the initial destination, later ones navigate.
    val pendingDeepLink = remember { mutableStateOf(initialDeepLink) }
    fun consumeDeepLink(route: String?) {
        if (route.isNullOrBlank()) return
        try {
            navController.navigate(route) {
                launchSingleTop = true
            }
        } catch (_: IllegalArgumentException) {
            // Route not registered yet: never crash the app over a link.
        }
    }
    LaunchedEffect(Unit) { consumeDeepLink(pendingDeepLink.value) }
    (context as? MainActivity)?.let { activity ->
        LaunchedEffect(activity.deepLinkRoute.value) {
            consumeDeepLink(activity.deepLinkRoute.value)
            activity.deepLinkRoute.value = null
        }
    }

    NavHost(navController = navController, startDestination = startDestination) {
        composable("connect") {
            ConnectScreen(serverConfig = serverConfig, onConnected = onConnected)
        }
        composable("home") {
            HomeScreen(navController = navController)
        }
        composable("videos") {
            VideosScreen(navController = navController)
        }
        composable(
            route = "search?query={query}",
            arguments = listOf(
                navArgument("query") {
                    type = NavType.StringType
                    defaultValue = ""
                }
            ),
        ) {
            val query = it.arguments?.getString("query").orEmpty()
            SearchScreen(navController = navController, initialQuery = query)
        }
        composable("history") {
            HistoryScreen(navController = navController)
        }
        composable("youtube") {
            YouTubeScreen(navController = navController)
        }
        composable("library") {
            LibraryScreen(
                navController = navController,
                onNavigateToSettings = { navController.navigate("settings") },
            )
        }
        composable("live") {
            LiveScreen(
                navController = navController,
                onNavigateToSettings = { navController.navigate("settings") },
            )
        }
        composable("local") {
            LocalScreen(navController = navController)
        }
        composable("channels") {
            ChannelsScreen(navController = navController)
        }
        composable(
            route = "channel_videos/{channelName}",
            arguments = listOf(navArgument("channelName") { type = NavType.StringType })
        ) { backStackEntry ->
            val channelName = backStackEntry.arguments?.getString("channelName").orEmpty()
            ChannelVideosScreen(channelName = channelName, navController = navController)
        }
        composable("local_player") {
            LocalPlayerScreen(navController = navController)
        }
        composable(
            route = "player/{itemId}?srtUrl={srtUrl}&sourceUrl={sourceUrl}&title={title}&mediaUrl={mediaUrl}",
            arguments = listOf(
                navArgument("itemId") { type = NavType.StringType },
                navArgument("srtUrl") { type = NavType.StringType; defaultValue = "" },
                navArgument("sourceUrl") { type = NavType.StringType; defaultValue = "" },
                navArgument("title") { type = NavType.StringType; defaultValue = "" },
                navArgument("mediaUrl") { type = NavType.StringType; defaultValue = "" },
            )
        ) { backStackEntry ->
            val itemId = backStackEntry.arguments?.getString("itemId").orEmpty()
            val sourceUrl = backStackEntry.arguments?.getString("sourceUrl").orEmpty()
            val srtUrl = backStackEntry.arguments?.getString("srtUrl").orEmpty()
            val title = backStackEntry.arguments?.getString("title").orEmpty()
            val mediaUrl = backStackEntry.arguments?.getString("mediaUrl").orEmpty()
            PlayerScreen(
                itemId = itemId,
                sourceUrl = sourceUrl,
                srtUrl = srtUrl,
                title = title,
                navController = navController,
                mediaUrl = mediaUrl,
            )
        }
        composable("settings") {
            SettingsScreen(navController = navController)
        }
    }
}