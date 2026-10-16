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
    "Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/ProtectAnAPI/" +
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
        failedAt: "navigate-expose-api",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }
  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-expose-api",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const applicationUri = page.getByRole("textbox", {
    name: "Copy the App ID URI to clipboard",
    exact: true,
  });
  const scope = page.getByText(`api://${appId}/user_impersonation`, {
    exact: true,
  });
  const connector = page.getByText(
    "4e4707ca-5f53-46a6-a819-f7765446e6ff",
    { exact: true },
  );
  const fields = [
    {
      label: "Application ID URI",
      locator: applicationUri,
    },
    {
      label: "Scopes defined by this API: user_impersonation",
      locator: scope,
    },
    {
      label: "Authorized client applications: Workday connector",
      locator: connector,
    },
  ];
  for (const field of fields) {
    try {
      await field.locator.first().waitFor({
        state: "visible",
        timeout: 10000,
      });
    } catch (error) {
      return {
        ok: false,
        failedAt: `wait-for-${field.label
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "")}`,
        url: page.url(),
        error: error.message,
      };
    }
    const count = await field.locator.count();
    if (count !== 1) {
      return {
        ok: false,
        failedAt: `locate-${field.label
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "")}`,
        url: page.url(),
        matchCount: count,
      };
    }
  }

  await connector.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const targets = [];
  for (const field of fields) {
    const box = await field.locator.boundingBox();
    if (!box) {
      return {
        ok: false,
        failedAt: `measure-${field.label
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "")}`,
        url: page.url(),
      };
    }
    const center = box.y + box.height / 2;
    targets.push({
      label: field.label,
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
    result.value = [
      `Application ID URI: ${(await applicationUri.inputValue()).trim()}`,
      `Scope: api://${appId}/user_impersonation`,
      "Authorized connector: 4e4707ca-5f53-46a6-a819-f7765446e6ff",
    ].join("; ");
  }
  return result;
};
