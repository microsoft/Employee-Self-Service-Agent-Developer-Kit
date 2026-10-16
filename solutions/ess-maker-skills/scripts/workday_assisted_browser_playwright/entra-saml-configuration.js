async (page, options = {}) => {
  const capture = options.capture !== false;
  const applicationUrl =
    typeof options.applicationUrl === "string"
      ? options.applicationUrl.trim()
      : "";
  if (!applicationUrl.includes("ManagedAppMenuBlade/~/Overview/")) {
    return {
      ok: false,
      failedAt: "missing-application-url",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const expectedUrl = applicationUrl.replace(
    "ManagedAppMenuBlade/~/Overview/",
    "ManagedAppMenuBlade/~/SignOn/",
  );
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
        failedAt: "navigate-saml-sign-on",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }
  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-saml-sign-on",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const loginUrlLabel = page.getByText("Login URL", { exact: true });
  const loginUrlLabelCount = await loginUrlLabel.count();
  if (loginUrlLabelCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-login-url-label",
      url: page.url(),
      matchCount: loginUrlLabelCount,
    };
  }
  try {
    await loginUrlLabel.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "wait-for-login-url-label",
      url: page.url(),
      error: error.message,
    };
  }
  const loginUrlRow = loginUrlLabel.locator(
    "xpath=ancestor::*[contains(@class, 'ext-saml-row')][1]",
  );
  if ((await loginUrlRow.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-login-url-row",
      url: page.url(),
      matchCount: await loginUrlRow.count(),
    };
  }

  await loginUrlLabel.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await loginUrlLabel.boundingBox();
  if (!box) {
    return {
      ok: false,
      failedAt: "measure-login-url",
      url: page.url(),
    };
  }
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const center = box.y + box.height / 2;
  const result = {
    ok: true,
    targets: [
      {
        label: "Set up Workday: Login URL",
        positionRatio:
          Math.round(
            Math.min(Math.max(center / viewport.height, 0.05), 0.95) * 10000,
          ) / 10000,
        centered:
          Math.abs(center - viewport.height / 2) <=
          Math.max(24, box.height / 2),
      },
    ],
  };
  if (capture) {
    const loginUrl = loginUrlRow.locator('input[type="text"]');
    const loginUrlCount = await loginUrl.count();
    if (loginUrlCount !== 1) {
      return {
        ok: false,
        failedAt: "locate-login-url-value",
        url: page.url(),
        matchCount: loginUrlCount,
      };
    }
    result.value = `Login URL: ${(await loginUrl.inputValue()).trim()}`;
  }
  return result;
};
