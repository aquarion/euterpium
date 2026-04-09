using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
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

        private readonly string _currentGamePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Playnite",
            "euterpium_current_game.json"
        );

        public override Guid Id { get; } = Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

        public EuterpiumExporter(IPlayniteAPI api) : base(api) { }

        public override void OnApplicationStarted(OnApplicationStartedEventArgs args)
        {
            // Clear any stale file left by a previous crash
            if (File.Exists(_currentGamePath))
            {
                try
                {
                    File.Delete(_currentGamePath);
                    logger.Info("EuterpiumExporter: cleared stale current game file on startup");
                }
                catch (Exception ex)
                {
                    logger.Warn($"EuterpiumExporter: failed to clear stale current game file '{_currentGamePath}': {ex.Message}");
                }
            }

            logger.Info("EuterpiumExporter: ready");
        }

        public override void OnGameStarted(OnGameStartedEventArgs args)
        {
            var game = args.Game;
            string exeName = null;

            // Prefer the actual process name from the PID Playnite gives us
            if (args.StartedProcessId.HasValue)
            {
                try
                {
                    var proc = Process.GetProcessById(args.StartedProcessId.Value);
                    exeName = proc.MainModule?.ModuleName;
                }
                catch (Exception ex)
                {
                    logger.Warn($"EuterpiumExporter: could not get process name from PID {args.StartedProcessId}: {ex.Message}");
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

            var entry = new CurrentGameEntry
            {
                Process = exeName,
                Name = game.Name,
                Pid = args.StartedProcessId,
            };

            var currentGameJson = JsonConvert.SerializeObject(entry, Formatting.Indented);
            WriteCurrentGameFileAtomically(currentGameJson);
            logger.Info($"EuterpiumExporter: game started — {game.Name} ({exeName})");
        }

        private void WriteCurrentGameFileAtomically(string contents)
        {
            var directory = Path.GetDirectoryName(_currentGamePath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var tempPath = Path.Combine(
                directory ?? string.Empty,
                Path.GetFileName(_currentGamePath) + "." + Guid.NewGuid().ToString("N") + ".tmp"
            );

            try
            {
                File.WriteAllText(tempPath, contents);

                if (File.Exists(_currentGamePath))
                {
                    File.Replace(tempPath, _currentGamePath, null);
                }
                else
                {
                    File.Move(tempPath, _currentGamePath);
                }
            }
            catch
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }

                throw;
            }
        }
        public override void OnGameStopped(OnGameStoppedEventArgs args)
        {
            if (File.Exists(_currentGamePath))
                File.Delete(_currentGamePath);

            logger.Info($"EuterpiumExporter: game stopped — {args.Game.Name}");
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

                    var exe = Path.GetFileName(resolved);
                    if (!string.IsNullOrWhiteSpace(exe))
                        return exe;
                }
            }

            if (string.IsNullOrWhiteSpace(game.InstallDirectory) ||
                !Directory.Exists(game.InstallDirectory))
                return null;

            try
            {
                var candidates = Directory
                    .GetFiles(game.InstallDirectory, "*.exe", SearchOption.TopDirectoryOnly)
                    .Select(Path.GetFileName)
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
                            Path.GetFileNameWithoutExtension(f)
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
    }

    internal class CurrentGameEntry
    {
        [JsonProperty("process")]
        public string Process { get; set; }

        [JsonProperty("name")]
        public string Name { get; set; }

        [JsonProperty("pid")]
        public int? Pid { get; set; }
    }
}
