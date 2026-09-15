package com.halffd.whispersubs

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavGraphBuilder
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.compose.navArgument
import androidx.navigation.NavType
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.ui.theme.WhisperSubsTheme
import com.halffd.whispersubs.ui.connect.ConnectScreen
import com.halffd.whispersubs.ui.library.LibraryScreen
import com.halffd.whispersubs.ui.live.LiveScreen
import com.halffd.whispersubs.ui.player.PlayerScreen
import com.halffd.whispersubs.ui.settings.SettingsScreen
import com.halffd.whispersubs.ui.local.LocalScreen
import com.halffd.whispersubs.ui.local.LocalPlayerScreen
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var serverConfig: ServerConfig

    @Inject
    lateinit var apiClient: ApiClient

    private val isConnected by remember { mutableStateOf(false) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        isConnected = serverConfig.isConfigured()
        setContent {
            WhisperSubsTheme {
                Surface {
                    NavHost(rememberNavController(), startDestination = if (isConnected) "library" else "connect") {
                        composable("connect") {
                            ConnectScreen(onConnected = { isConnected = true })
                        }
                        composable("library") {
                            LibraryScreen(onNavigateToSettings = { navController.navigate("settings") })
                        }
                        composable("live") {
                            LiveScreen(onNavigateToSettings = { navController.navigate("settings") })
                        }
                        composable("local") {
                            LocalScreen()
                        }
                        composable("local_player") {
                            LocalPlayerScreen(navController)
                        }
                        composable(
                            route = "player/{itemId}",
                            arguments = listOf(navArgument("itemId") { type = NavType.StringType })
                        ) { backStackEntry ->
                            val itemId = backStackEntry.getString()!!
                            val sourceUrl = backStackEntry.getString("sourceUrl") ?: ""
                            val srtUrl = backStackEntry.getString("srtUrl") ?: ""
                            val title = backStackEntry.getString("title") ?: ""
                            PlayerScreen(
                                itemId = itemId,
                                sourceUrl = sourceUrl,
                                srtUrl = srtUrl,
                                title = title
                            )
                        }
                        composable("settings") {
                            SettingsScreen()
                        }
                    }
                }
            }
        }
    }
}