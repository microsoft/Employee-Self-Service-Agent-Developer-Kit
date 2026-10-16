async (page, options = {}) => {
  const capture = options.capture !== false;
  const applicationUrl =
    typeof options.applicationUrl === "string"
      ? options.applicationUrl.trim()
      : "";
  const appIdMatch = applicationUrl.match(
    /ManagedAppMenuBlade\/~\/Overview\/.*\/appId\/([0-9a-f-]{36})\//i,
  );
  if (!appIdMatch) {
    return {
      ok: false,
      failedAt: "missing-application-url",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const appId = appIdMatch[1];
  const expectedUrl =
    "https://entra.microsoft.com/#view/" +
    "Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/CallAnAPI/" +
    `appId/${appId}/isMSAApp~/false`;
  if (page.url() !== expectedUrl) {
    try {
      await page.goto(expectedUrl);
      await page.waitForURL(expectedUrl, { timeout: 10000 });
      await page.locator(".fxs-splashscreen").waitFor({
        state: "hidden",
        timeout: 15000,
      });
    } catch {
      return {
        ok: false,
        failedAt: "navigate-api-permissions",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }
  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-api-permissions",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const grantedConsent = /^Granted for .+/i;
  const permissionRows = [];
  for (const permissionName of ["openid", "profile", "User.Read"]) {
    const permission = page.getByText(permissionName, { exact: true });
    try {
      await permission.first().waitFor({
        state: "visible",
        timeout: 10000,
      });
    } catch (error) {
      return {
        ok: false,
        failedAt: "wait-for-delegated-permission",
        permission: permissionName,
        url: page.url(),
        error: error.message,
      };
    }
    if ((await permission.count()) !== 1) {
      return {
        ok: false,
        failedAt: "locate-delegated-permission",
        permission: permissionName,
        url: page.url(),
        matchCount: await permission.count(),
      };
    }
    const permissionRow = permission.locator(
      'xpath=ancestor::*[@role="row" or self::tr][1]',
    );
    if ((await permissionRow.count()) !== 1) {
      return {
        ok: false,
        failedAt: "locate-permission-row",
        permission: permissionName,
        url: page.url(),
        matchCount: await permissionRow.count(),
      };
    }
    const consent = permissionRow.getByText(grantedConsent);
    try {
      await consent.first().waitFor({
        state: "visible",
        timeout: 10000,
      });
    } catch (error) {
      return {
        ok: false,
        failedAt: "wait-for-admin-consent",
        permission: permissionName,
        url: page.url(),
        error: error.message,
      };
    }
    if ((await consent.count()) !== 1) {
      return {
        ok: false,
        failedAt: "verify-admin-consent",
        permission: permissionName,
        url: page.url(),
        matchCount: await consent.count(),
      };
    }
    permissionRows.push({ permissionName, permissionRow });
  }

  await permissionRows.at(-1).permissionRow.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const targets = [];
  for (const { permissionName, permissionRow } of permissionRows) {
    const box = await permissionRow.boundingBox();
    if (!box) {
      return {
        ok: false,
        failedAt: "measure-permission-row",
        permission: permissionName,
        url: page.url(),
      };
    }
    const center = box.y + box.height / 2;
    targets.push({
      label: `${permissionName} delegated permission with admin consent`,
      positionRatio:
        Math.round(
          Math.min(Math.max(center / viewport.height, 0.05), 0.95) * 10000,
        ) / 10000,
      centered:
        Math.abs(center - viewport.height / 2) <=
        Math.max(24, box.height / 2),
    });
  }

  const result = {
    ok: true,
    targets,
  };
  if (capture) {
    result.value =
      "openid, profile, and User.Read are visible with administrator consent granted.";
  }
  return result;
};
