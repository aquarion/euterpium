using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Playnite.SDK;
using Playnite.SDK.Events;
using Playnite.SDK.Models;
using Playnite.SDK.Plugins;

namespace EuterpiumExporter
{
    public class EuterpiumExporter : GenericPlugin
    {
        private static readonly ILogger logger = LogManager.GetLogger();

        // Exe name substrings (lowercase) for distinctive support binaries that are
        // not the main game executable, used as a fallback when Playnite doesn't
        // provide a process ID. Keep these specific to avoid excluding real games.
        private static readonly string[] _nonGameExePatterns = new[]
        {
            "unins", "setup", "install", "redist", "vcredist", "dxsetup",
            "dotnet", "crashreporter", "crashpad_handler", "reporter", "launcher_fixes",
            "steam_", "easyanticheat", "eac_launcher", "battleye", "be_service",
        };

        // Resolved once at startup from euterpium.ini so port and auth key follow the app config.
        // _apiKey is volatile so it can be refreshed on 401 (e.g. if Playnite started before
        // Euterpium's first run, when no key exists yet). Port changes require a Playnite restart.
        private static readonly string _apiBaseUrl = BuildApiBaseUrl();
        private static volatile string _apiKey = ReadKeyFromConfig();
        private static readonly HttpClient _httpClient = CreateHttpClient();

        // Tracks whether the last API call succeeded so we only notify on the first failure
        // and clear the notification when connectivity is restored.
        // _lastNotificationMessage lets us update the notification if the failure reason changes.
        private const string NotificationId = "euterpium-api-error";
        private volatile bool _apiReachable = true;
        private volatile string _lastNotificationMessage = null;

        public override Guid Id { get; } = Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

        public EuterpiumExporter(IPlayniteAPI api) : base(api) { }

        public override void OnApplicationStarted(OnApplicationStartedEventArgs args)
        {
            var version = ReadPluginVersion();
            logger.Info($"EuterpiumExporter v{version} ready — API at {_apiBaseUrl}/api/");

            // Remove legacy file written by the old file-based integration (pre-REST API).
            try
            {
                var legacyPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Playnite",
                    "euterpium_current_game.json"
                );
                if (File.Exists(legacyPath))
                {
                    File.Delete(legacyPath);
                    logger.Info("EuterpiumExporter: removed legacy euterpium_current_game.json");
                }
            }
            catch (Exception ex)
            {
                logger.Warn($"EuterpiumExporter: could not remove legacy game file: {ex.Message}");
            }
        }

        public override void OnGameStarted(OnGameStartedEventArgs args)
        {
            var game = args.Game;
            string exeName = null;

            // Prefer the actual process name from the PID Playnite gives us.
            // ProcessName (rather than MainModule.ModuleName) works when Playnite is
            // 32-bit and the game is 64-bit — MainModule requires same-bitness access.
            var pid = args.StartedProcessId;
            if (pid > 0)
            {
                try
                {
                    using var proc = Process.GetProcessById((int)pid);
                    exeName = proc.ProcessName + ".exe";
                }
                catch (Exception ex)
                {
                    logger.Warn($"EuterpiumExporter: could not get process name from PID {pid}: {ex.Message}");
                }
            }

            // Fall back to resolving from game configuration / install directory
            if (string.IsNullOrWhiteSpace(exeName))
                exeName = FindGameExe(game);

            if (string.IsNullOrWhiteSpace(exeName))
            {
                logger.Warn($"EuterpiumExporter: could not determine exe for '{game.Name}' — game will not be detected");
                return;
            }

            // Build payload using the already-resolved pid variable; treat 0 as absent.
            var payload = JsonConvert.SerializeObject(new
            {
                process = exeName,
                name = game.Name,
                pid = pid > 0 ? (int?)pid : null,
            });

            PostToEuterpiumApi("/api/game/start", payload);
            logger.Info($"EuterpiumExporter: game started — {game.Name} ({exeName})");
        }

        public override void OnGameStopped(OnGameStoppedEventArgs args)
        {
            PostToEuterpiumApi("/api/game/stop", "{}");
            logger.Info($"EuterpiumExporter: game stopped — {args.Game.Name}");
        }

        private void PostToEuterpiumApi(string path, string json)
        {
            try
            {
                var status = SendPost(path, json);
                if (status == System.Net.HttpStatusCode.Unauthorized)
                {
                    // Key may have been generated after Playnite loaded — refresh and retry once
                    // so the triggering event (e.g. game start) is not silently dropped.
                    _apiKey = ReadKeyFromConfig();
                    status = SendPost(path, json);
                }

                if (status == System.Net.HttpStatusCode.Unauthorized)
                {
                    if (string.IsNullOrWhiteSpace(_apiKey))
                    {
                        OnApiFailure(
                            $"EuterpiumExporter: API call to {path} returned 401 Unauthorized — " +
                            "no [rest_api] key is configured in euterpium.ini or the plugin could not read it",
                            "Euterpium: no API token configured/read — open euterpium.ini and set [rest_api] key"
                        );
                    }
                    else
                    {
                        OnApiFailure(
                            $"EuterpiumExporter: API call to {path} returned 401 Unauthorized — " +
                            "check that [rest_api] key in euterpium.ini matches between the app and plugin",
                            "Euterpium: bearer token mismatch — open euterpium.ini and check [rest_api] key"
                        );
                    }
                }
                else if ((int)status < 200 || (int)status >= 300)
                {
                    OnApiFailure(
                        $"EuterpiumExporter: API call to {path} returned {(int)status}",
                        $"Euterpium: unexpected response {(int)status} from local API"
                    );
                }
                else
                {
                    OnApiSuccess();
                }
            }
            catch (Exception ex)
            {
                OnApiFailure(
                    $"EuterpiumExporter: API call to {path} failed: {ex.Message}",
                    "Euterpium: could not reach local API — is Euterpium running?"
                );
            }
        }

        /// <summary>
        /// Sends a single POST and returns the HTTP status code.
        /// Creates fresh content/request objects each call so it is safe to call twice.
        /// </summary>
        private System.Net.HttpStatusCode SendPost(string path, string json)
        {
            // Task.Run detaches from any ambient SynchronizationContext, avoiding
            // the deadlock that GetAwaiter().GetResult() can cause on .NET Framework.
            using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
            using (var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = content })
            {
                var currentKey = _apiKey;
                if (!string.IsNullOrEmpty(currentKey))
                    request.Headers.Authorization =
                        new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", currentKey);
                using (var response = Task.Run(() => _httpClient.SendAsync(request)).GetAwaiter().GetResult())
                    return response.StatusCode;
            }
        }

        private void OnApiSuccess()
        {
            if (_apiReachable)
                return;
            _apiReachable = true;
            _lastNotificationMessage = null;
            PlayniteApi.Notifications.Remove(NotificationId);
            logger.Info("EuterpiumExporter: API connection restored");
        }

        private void OnApiFailure(string logMessage, string notificationMessage)
        {
            logger.Warn(logMessage);
            if (!_apiReachable && notificationMessage == _lastNotificationMessage)
                return;
            _apiReachable = false;
            _lastNotificationMessage = notificationMessage;
            PlayniteApi.Notifications.Add(new NotificationMessage(
                NotificationId,
                notificationMessage,
                NotificationType.Error
            ));
        }

        // Fallback exe resolution when Playnite doesn't provide a process ID.
        // Tries explicit File-type play actions first, then scans the install directory.
        private string FindGameExe(Game game)
        {
            if (game.GameActions != null)
            {
                foreach (var action in game.GameActions)
                {
                    if (!action.IsPlayAction || action.Type != GameActionType.File)
                        continue;

                    var resolved = PlayniteApi.ExpandGameVariables(game, action.Path);
                    if (string.IsNullOrWhiteSpace(resolved))
                        continue;

                    var exe = System.IO.Path.GetFileName(resolved);
                    if (!string.IsNullOrWhiteSpace(exe))
                        return exe;
                }
            }

            if (string.IsNullOrWhiteSpace(game.InstallDirectory) ||
                !System.IO.Directory.Exists(game.InstallDirectory))
                return null;

            try
            {
                var candidates = System.IO.Directory
                    .GetFiles(game.InstallDirectory, "*.exe", System.IO.SearchOption.TopDirectoryOnly)
                    .Select(System.IO.Path.GetFileName)
                    .Where(f => !IsNonGameExe(f))
                    .ToList();

                if (candidates.Count == 1)
                    return candidates[0];

                if (candidates.Count > 1)
                {
                    var slug = new string(game.Name
                        .ToLowerInvariant()
                        .Where(char.IsLetterOrDigit)
                        .ToArray());

                    return candidates.FirstOrDefault(f =>
                    {
                        var nameSlug = new string(
                            System.IO.Path.GetFileNameWithoutExtension(f)
                                .ToLowerInvariant()
                                .Where(char.IsLetterOrDigit)
                                .ToArray());
                        return nameSlug.Contains(slug) || slug.Contains(nameSlug);
                    });
                }
            }
            catch (Exception ex)
            {
                logger.Warn($"EuterpiumExporter: could not scan install dir for '{game.Name}': {ex.Message}");
            }

            return null;
        }

        private static bool IsNonGameExe(string filename)
        {
            var lower = filename.ToLowerInvariant();
            return _nonGameExePatterns.Any(p => lower.Contains(p));
        }

        private static HttpClient CreateHttpClient()
        {
            return new HttpClient
            {
                BaseAddress = new Uri(_apiBaseUrl),
                Timeout = TimeSpan.FromSeconds(2),
            };
        }

        private static string BuildApiBaseUrl()
        {
            int port = ReadPortFromConfig();
            return $"http://127.0.0.1:{port}";
        }

        /// <summary>
        /// Reads the [rest_api] key from euterpium.ini. Returns an empty string if
        /// the file is absent or the key has not been generated yet. The server
        /// auto-generates a key on first run; if Playnite started before that first
        /// run, subsequent 401 responses will trigger a refresh via <see cref="_apiKey"/>.
        /// </summary>
        private static string ReadKeyFromConfig()
        {
            return ReadIniValue("rest_api", "key", string.Empty);
        }

        /// <summary>
        /// Reads the [rest_api] port from euterpium.ini so the plugin follows
        /// the same port the app is listening on. Falls back to 43174 if the
        /// file is absent or the port value is missing/invalid.
        /// </summary>
        private static int ReadPortFromConfig()
        {
            var raw = ReadIniValue("rest_api", "port", "43174");
            if (int.TryParse(raw, out int port) && port >= 1024 && port <= 65535)
                return port;
            return 43174;
        }

        /// <summary>
        /// Reads the Version field from extension.yaml, which is deployed alongside the DLL.
        /// Returns "unknown" if the file is absent or the field can't be parsed.
        /// </summary>
        private static string ReadPluginVersion()
        {
            try
            {
                var yamlPath = Path.Combine(
                    Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location),
                    "extension.yaml"
                );
                foreach (var line in File.ReadLines(yamlPath))
                {
                    var trimmed = line.Trim();
                    if (trimmed.StartsWith("Version:", StringComparison.OrdinalIgnoreCase))
                        return trimmed.Substring("Version:".Length).Trim();
                }
            }
            catch (Exception ex)
            {
                logger.Warn($"EuterpiumExporter: could not read plugin version from extension.yaml: {ex.Message}");
            }
            return "unknown";
        }

        /// <summary>
        /// Reads a single key from a section of euterpium.ini
        /// (%LOCALAPPDATA%\euterpium\euterpium.ini). Returns <paramref name="fallback"/>
        /// if the file, section, or key is absent, or on any read error.
        /// </summary>
        private static string ReadIniValue(string section, string key, string fallback)
        {
            try
            {
                var configPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "euterpium",
                    "euterpium.ini"
                );

                if (!File.Exists(configPath))
                    return fallback;

                var sectionHeader = $"[{section}]";
                bool inSection = false;
                foreach (var line in File.ReadLines(configPath))
                {
                    var trimmed = line.Trim();
                    if (trimmed.StartsWith("["))
                    {
                        inSection = trimmed.Equals(sectionHeader, StringComparison.OrdinalIgnoreCase);
                        continue;
                    }
                    if (!inSection)
                        continue;
                    if (trimmed.StartsWith(";") || trimmed.StartsWith("#"))
                        continue;

                    var eqIdx = trimmed.IndexOf('=');
                    if (eqIdx < 0)
                        continue;

                    var parsedKey = trimmed.Substring(0, eqIdx).Trim();
                    if (!parsedKey.Equals(key, StringComparison.OrdinalIgnoreCase))
                        continue;

                    var value = trimmed.Substring(eqIdx + 1).Trim();
                    // Strip inline comments (; or #)
                    var commentIdx = value.IndexOfAny(new[] { ';', '#' });
                    if (commentIdx >= 0)
                        value = value.Substring(0, commentIdx).Trim();

                    return value;
                }
            }
            catch
            {
                // Fall through to fallback — logger not available in static context
            }
            return fallback;
        }
    }
}
