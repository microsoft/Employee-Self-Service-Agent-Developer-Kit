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
    "ManagedAppMenuBlade/~/Users/",
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
        failedAt: "navigate-users-and-groups",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }
  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-users-and-groups",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const heading = page.getByRole("heading", {
    name: /\| Users and groups$/,
  });
  try {
    await heading.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "wait-for-users-and-groups",
      url: page.url(),
      matchCount: await heading.count(),
      error: error.message,
    };
  }

  const result = { ok: true };
  if (capture) {
    result.value = "The Users and groups page is open for assignment review.";
  }
  return result;
};
