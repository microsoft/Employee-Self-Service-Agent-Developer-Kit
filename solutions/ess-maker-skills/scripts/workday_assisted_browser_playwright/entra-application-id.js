async (page, options = {}) => {
  const capture = options.capture !== false;
  const suppliedApplicationUrl =
    typeof options.applicationUrl === "string"
      ? options.applicationUrl.trim()
      : "";
  const expectedUrl =
    suppliedApplicationUrl ||
    (page.url().includes("ManagedAppMenuBlade/~/Overview/")
      ? page.url()
      : "");
  if (!expectedUrl.includes("ManagedAppMenuBlade/~/Overview/")) {
    return {
      ok: false,
      failedAt: "missing-application-url",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  if (page.url() !== expectedUrl) {
    try {
      await page.goto(expectedUrl);
      await page.waitForURL(expectedUrl, { timeout: 10000 });
    } catch {
      return {
        ok: false,
        failedAt: "navigate-application-overview",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }

  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-application-overview",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const applicationId = page.getByRole("textbox", {
    name: "Application ID",
    exact: true,
  });
  try {
    await applicationId.waitFor({ state: "visible", timeout: 5000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-application-id",
      url: page.url(),
      matchCount: await applicationId.count(),
      error: error.message,
    };
  }

  const value = capture ? (await applicationId.inputValue()).trim() : null;
  if (capture && !value) {
    return {
      ok: false,
      failedAt: "read-application-id",
      url: page.url(),
    };
  }

  await applicationId.scrollIntoViewIfNeeded();
  const box = await applicationId.boundingBox();
  if (!box) {
    return {
      ok: false,
      failedAt: "measure-application-id",
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
        label: "Application ID",
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
