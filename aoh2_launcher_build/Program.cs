using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static void Main()
    {
        try
        {
            string exeDir = AppDomain.CurrentDomain.BaseDirectory;
            string gameDir = FindGameDirectory(exeDir);

            if (gameDir == null)
            {
                ShowError(
                    "Не удалось найти папку игры.\n\n" +
                    "Положи этот .exe в папку, где лежит game.jar,\n" +
                    "или на уровень выше папки с игрой.");
                return;
            }

            string jarPath = Path.Combine(gameDir, "game.jar");
            string javaPath = FindJavaExecutable(gameDir);

            if (javaPath == null)
            {
                ShowError(
                    "Не найден javaw.exe для запуска игры.\n\n" +
                    "Ожидался файл:\n" +
                    Path.Combine(gameDir, "jre", "bin", "javaw.exe"));
                return;
            }

            var startInfo = new ProcessStartInfo
            {
                FileName = javaPath,
                Arguments = "-jar \"" + jarPath + "\"",
                WorkingDirectory = gameDir,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            Process.Start(startInfo);
        }
        catch (Exception ex)
        {
            ShowError("Не удалось запустить игру.\n\n" + ex.Message);
        }
    }

    private static string FindGameDirectory(string exeDir)
    {
        foreach (string dir in EnumerateCandidateDirectories(exeDir))
        {
            if (File.Exists(Path.Combine(dir, "game.jar")))
            {
                return dir;
            }
        }

        return null;
    }

    private static IEnumerable<string> EnumerateCandidateDirectories(string exeDir)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var candidates = new List<string>();

        AddIfNew(candidates, seen, exeDir);

        DirectoryInfo parentInfo = Directory.GetParent(exeDir);
        if (parentInfo != null)
        {
            AddIfNew(candidates, seen, parentInfo.FullName);
        }

        string[] roots = candidates.ToArray();
        foreach (string root in roots)
        {
            try
            {
                foreach (string subDir in Directory.GetDirectories(root))
                {
                    AddIfNew(candidates, seen, subDir);
                }
            }
            catch
            {
            }
        }

        return candidates;
    }

    private static void AddIfNew(List<string> candidates, HashSet<string> seen, string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        string fullPath;
        try
        {
            fullPath = Path.GetFullPath(path);
        }
        catch
        {
            return;
        }

        if (seen.Add(fullPath))
        {
            candidates.Add(fullPath);
        }
    }

    private static string FindJavaExecutable(string gameDir)
    {
        string[] preferred =
        {
            Path.Combine(gameDir, "jre", "bin", "javaw.exe"),
            Path.Combine(gameDir, "jre", "bin", "java.exe")
        };

        foreach (string path in preferred)
        {
            if (File.Exists(path))
            {
                return path;
            }
        }

        return null;
    }

    private static void ShowError(string message)
    {
        MessageBox.Show(
            message,
            "Age of History 2 DE Launcher",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error);
    }
}
