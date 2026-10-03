using System;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Windows <c>Util.credits</c>.</summary>
public static class CreditFormat
{
    public static string Credits(long credits, bool hideUnits = false)
    {
        string txt;
        if (credits < 1_000)
            txt = credits.ToString("N0");
        else if (credits < 100_000)
            txt = (credits / 1_000d).ToString("#.##") + " K";
        else if (credits < 1_000_000)
            txt = (credits / 1_000d).ToString("#") + " K";
        else if (credits < 100_000_000)
            txt = (credits / 1_000_000d).ToString("#.##") + " M";
        else if (credits < 1_000_000_000)
            txt = (credits / 1_000_000d).ToString("#") + " M";
        else
            txt = (credits / 1_000_000_000d).ToString("#.###") + " B";

        if (!hideUnits)
            txt += " CR";
        return txt;
    }
}
