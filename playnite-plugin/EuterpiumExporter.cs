using System;
using System.Collections.Generic;
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

        private readonly string _exportPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Playnite",
            "euterpium_games.json"
        );

        public override Guid Id { get; } = Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

        public EuterpiumExporter(IPlayniteAPI api) : base(api) { }

        public override void OnApplicationStarted(OnApplicationStartedEventArgs args)
        {
            ExportGames();
            PlayniteApi.Database.Games.ItemCollectionChanged += (_, __) => ExportGames();
        }

        private void ExportGames()
        {
            try
            {
                var entries = new List<GameEntry>();

                foreach (var game in PlayniteApi.Database.Games)
                {
                    if (game.GameActions == null)
                        continue;

                    foreach (var action in game.GameActions)
                    {
                        if (!action.IsPlayAction || action.Type != GameActionType.File)
                            continue;

                        var resolvedPath = PlayniteApi.ExpandGameVariables(game, action.Path);
                        if (string.IsNullOrWhiteSpace(resolvedPath))
                            continue;

                        var exe = Path.GetFileName(resolvedPath);
                        if (string.IsNullOrWhiteSpace(exe))
                            continue;

                        entries.Add(new GameEntry { Process = exe, Name = game.Name });
                        break; // one entry per game
                    }
                }

                var json = JsonConvert.SerializeObject(entries, Formatting.Indented);
                File.WriteAllText(_exportPath, json);
                logger.Info($"EuterpiumExporter: exported {entries.Count} game(s) to {_exportPath}");
            }
            catch (Exception ex)
            {
                logger.Error(ex, "EuterpiumExporter: failed to export games");
            }
        }
    }

    internal class GameEntry
    {
        [JsonProperty("process")]
        public string Process { get; set; }

        [JsonProperty("name")]
        public string Name { get; set; }
    }
}
