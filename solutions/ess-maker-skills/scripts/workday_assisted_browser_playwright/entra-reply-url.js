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

  const replyUrlLabel = page.getByText(
    "Reply URL (Assertion Consumer Service URL)",
    { exact: true },
  );
  try {
    await replyUrlLabel.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-reply-url-label",
      url: page.url(),
      matchCount: await replyUrlLabel.count(),
      error: error.message,
    };
  }

  const replyUrl = page.getByText(
    "https://impl.workday.com/microsoft_dpt6/login-saml.htmld",
    { exact: true },
  );
  try {
    await replyUrl.first().waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-reply-url",
      url: page.url(),
      matchCount: await replyUrl.count(),
      error: error.message,
    };
  }

  const value = capture ? (await replyUrl.first().innerText()).trim() : null;
  await replyUrl.first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await replyUrl.first().boundingBox();
  if (!box) {
    return { ok: false, failedAt: "measure-reply-url", url: page.url() };
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
        label: "Reply URL (Assertion Consumer Service URL)",
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
    result.value = value;
  }
  return result;
};
