package com.halffd.whispersubs

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.ui.channels.ChannelsScreen
import com.halffd.whispersubs.ui.channels.ChannelVideosScreen
import com.halffd.whispersubs.ui.connect.ConnectScreen
import com.halffd.whispersubs.ui.home.HomeScreen
import com.halffd.whispersubs.ui.home.VideosScreen
import com.halffd.whispersubs.ui.connect.ConnectScreen
import com.halffd.whispersubs.ui.library.LibraryScreen
import com.halffd.whispersubs.ui.live.LiveScreen
import com.halffd.whispersubs.ui.local.LocalPlayerScreen
import com.halffd.whispersubs.ui.local.LocalScreen
import com.halffd.whispersubs.ui.player.PlayerScreen
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

    private var isConnected by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        isConnected = serverConfig.isConfigured()
        setContent {
            WhisperSubsTheme {
                Surface {
                    AppNavHost(
                        startDestination = if (isConnected) "home" else "connect",
                        onConnected = { isConnected = true },
                        serverConfig = serverConfig,
                    )
                }
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun AppNavHost(
    startDestination: String,
    onConnected: () -> Unit,
    serverConfig: ServerConfig,
) {
    val navController: NavHostController = rememberNavController()

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
        composable("videos") {
            VideosScreen(navController = navController)
        }
        composable("local_player") {
            LocalPlayerScreen(navController = navController)
        }
        composable(
            route = "player/{itemId}?srtUrl={srtUrl}&sourceUrl={sourceUrl}&title={title}",
            arguments = listOf(
                navArgument("itemId") { type = NavType.StringType },
                navArgument("srtUrl") { type = NavType.StringType; defaultValue = "" },
                navArgument("sourceUrl") { type = NavType.StringType; defaultValue = "" },
                navArgument("title") { type = NavType.StringType; defaultValue = "" },
            )
        ) { backStackEntry ->
            val itemId = backStackEntry.arguments?.getString("itemId").orEmpty()
            val sourceUrl = backStackEntry.arguments?.getString("sourceUrl").orEmpty()
            val srtUrl = backStackEntry.arguments?.getString("srtUrl").orEmpty()
            val title = backStackEntry.arguments?.getString("title").orEmpty()
            PlayerScreen(
                itemId = itemId,
                sourceUrl = sourceUrl,
                srtUrl = srtUrl,
                title = title,
                navController = navController,
            )
        }
        composable("settings") {
            SettingsScreen(navController = navController)
        }
    }
}