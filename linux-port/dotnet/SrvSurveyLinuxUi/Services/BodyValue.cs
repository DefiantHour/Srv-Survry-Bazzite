using System;

namespace SrvSurveyLinuxUi.Services;

/// <summary>Windows <c>Util.GetBodyValue</c> / Python <c>body_value.get_body_value</c>.</summary>
public static class BodyValue
{
    public static bool IsStarClass(string? planetClass)
    {
        if (planetClass == null)
            return false;
        return planetClass.Length < 8
            || (planetClass.Length > 1 && planetClass[1] == '_')
            || planetClass is "SupermassiveBlackHole" or "Nebula" or "StellarRemnantNebula";
    }

    public static double StarKValue(string starClass)
    {
        var kk = 1200d;
        if (starClass is "NS" or "BH" or "SupermassiveBlackHole")
            kk = 22628;
        else if (starClass.Length > 0 && starClass[0] == 'W')
            kk = 14057;
        return kk;
    }

    public static double BodyKValue(string planetClass, bool isTerraformable)
    {
        if (planetClass == "Metal rich body")
            return 21790;
        if (planetClass == "Ammonia world")
            return 96932;
        if (planetClass == "Sudarsky class I gas giant")
            return 1656;
        if (planetClass is "Sudarsky class II gas giant" or "High metal content body")
            return 9654 + (isTerraformable ? 100677 : 0);
        if (planetClass == "Water world")
            return 64831 + (isTerraformable ? 116295 : 0);
        if (planetClass.StartsWith("Earth", StringComparison.Ordinal))
            return 64831 + 116295;
        return 300 + (isTerraformable ? 93328 : 0);
    }

    public static int GetBodyValue(
        string? planetClass,
        bool isTerraformable,
        double mass,
        bool isFirstDiscoverer,
        bool isMapped,
        bool isFirstMapped,
        bool withEfficiencyBonus = true,
        bool isOdyssey = true,
        bool isFleetCarrierSale = false)
    {
        if (IsStarClass(planetClass))
        {
            var kk = StarKValue(planetClass ?? "");
            return (int)Math.Round(kk + (mass * kk / 66.25));
        }

        var k = BodyKValue(planetClass ?? "", isTerraformable);
        const double q = 0.56591828;
        var mappingMultiplier = 1d;
        if (isMapped)
        {
            if (isFirstDiscoverer && isFirstMapped)
                mappingMultiplier = 3.699622554;
            else if (isFirstMapped)
                mappingMultiplier = 8.0956;
            else
                mappingMultiplier = 3.3333333333;
        }

        var value = (k + k * q * Math.Pow(Math.Max(mass, 0), 0.2)) * mappingMultiplier;
        if (isMapped)
        {
            if (isOdyssey)
                value += (value * 0.3) > 555 ? value * 0.3 : 555;
            if (withEfficiencyBonus)
                value *= 1.25;
        }

        value = Math.Max(500, value);
        value *= isFirstDiscoverer ? 2.6 : 1;
        value *= isFleetCarrierSale ? 0.75 : 1;
        return (int)Math.Round(value);
    }

    public static string BodyTypeFrom(string? starType, string? planetClass, bool landable, string? bodyName)
    {
        if (landable)
            return "LandableBody";
        if (!string.IsNullOrEmpty(starType))
            return "Star";
        if (!string.IsNullOrEmpty(bodyName) && bodyName.Contains("cluster", StringComparison.OrdinalIgnoreCase))
            return "Asteroid";
        if (!string.IsNullOrEmpty(bodyName) && bodyName.EndsWith("Ring", StringComparison.OrdinalIgnoreCase))
            return "PlanetaryRing";
        if (string.IsNullOrEmpty(starType) && string.IsNullOrEmpty(planetClass))
            return "Barycentre";
        if (planetClass?.Contains("giant", StringComparison.OrdinalIgnoreCase) == true)
            return "Giant";
        return "SolidBody";
    }
}
