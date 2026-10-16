async (page, options = {}) => {
  const capture = options.capture !== false;
  const destinationUrl =
    "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/StartboardApplicationsMenuBlade/~/AppAppsPreview";
  if (page.url() !== destinationUrl) {
    try {
      await page.goto(destinationUrl);
      await page.waitForURL(destinationUrl, { timeout: 10000 });
    } catch {
      return {
        ok: false,
        failedAt: "navigate-enterprise-applications",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }

  const filter = page.getByRole("searchbox", {
    name: "Search box",
    exact: true,
  });
  try {
    await filter.waitFor({ state: "visible", timeout: 5000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-application-filter",
      url: page.url(),
      matchCount: await filter.count(),
      error: error.message,
    };
  }

  try {
    await filter.fill("Workday");
  } catch (error) {
    return {
      ok: false,
      failedAt: "filter-applications",
      url: page.url(),
      error: error.message,
    };
  }

  const identifier = page.getByRole("gridcell").filter({
    hasText: /^http:\/\/www\.workday\.com\/microsoft_dpt6,/,
  });
  try {
    await identifier.waitFor({ state: "visible", timeout: 5000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-application-identifier",
      url: page.url(),
      filterValue: await filter.inputValue(),
      matchCount: await identifier.count(),
      error: error.message,
    };
  }

  const row = identifier.locator('xpath=ancestor::*[@role="row"][1]');
  const application = row.getByRole("link");
  try {
    await application.first().waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-enterprise-application",
      url: page.url(),
      filterValue: await filter.inputValue(),
      matchCount: await application.count(),
      error: error.message,
    };
  }
  const applicationCount = await application.count();
  if (applicationCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-enterprise-application",
      url: page.url(),
      filterValue: await filter.inputValue(),
      matchCount: applicationCount,
    };
  }

  const splash = page.locator(".fxs-splashscreen");
  if ((await splash.count()) > 0) {
    try {
      await splash.first().waitFor({ state: "hidden", timeout: 15000 });
    } catch (error) {
      return {
        ok: false,
        failedAt: "wait-for-application-results",
        url: page.url(),
        error: error.message,
      };
    }
  }

  try {
    await application.first().click();
    await page.waitForURL(
      (url) =>
        url.href.includes("ManagedAppMenuBlade/~/Overview/"),
      { timeout: 10000 },
    );
  } catch {
    return {
      ok: false,
      failedAt: "open-enterprise-application",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const displayName = page.getByRole("textbox", {
    name: "Name",
    exact: true,
  });
  try {
    await displayName.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-enterprise-application-name",
      url: page.url(),
      matchCount: await displayName.count(),
      error: error.message,
    };
  }

  const displayNameValue = capture
    ? (await displayName.inputValue()).trim()
    : null;
  if (capture && !displayNameValue) {
    return {
      ok: false,
      failedAt: "read-enterprise-application-name",
      url: page.url(),
    };
  }

  const applicationId = page.getByRole("textbox", {
    name: "Application ID",
    exact: true,
  });
  try {
    await applicationId.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-application-id",
      url: page.url(),
      matchCount: await applicationId.count(),
      error: error.message,
    };
  }

  const applicationIdValue = capture
    ? (await applicationId.inputValue()).trim()
    : null;
  if (capture && !applicationIdValue) {
    return {
      ok: false,
      failedAt: "read-application-id",
      url: page.url(),
    };
  }

  await displayName.scrollIntoViewIfNeeded();
  const displayNameBox = await displayName.boundingBox();
  if (!displayNameBox) {
    return {
      ok: false,
      failedAt: "measure-enterprise-application-name",
      url: page.url(),
    };
  }
  await applicationId.scrollIntoViewIfNeeded();
  const applicationIdBox = await applicationId.boundingBox();
  if (!applicationIdBox) {
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
  const displayNameCenter =
    displayNameBox.y + displayNameBox.height / 2;
  const applicationIdCenter =
    applicationIdBox.y + applicationIdBox.height / 2;
  const result = {
    ok: true,
    applicationUrl: page.url(),
    targets: [
      {
        label: "Enterprise application name",
        positionRatio:
          Math.round(
            Math.min(
              Math.max(displayNameCenter / viewport.height, 0.05),
              0.95,
            ) * 10000,
          ) / 10000,
        centered:
          Math.abs(displayNameCenter - viewport.height / 2) <=
          Math.max(24, displayNameBox.height / 2),
      },
      {
        label: "Application ID",
        positionRatio:
          Math.round(
            Math.min(
              Math.max(applicationIdCenter / viewport.height, 0.05),
              0.95,
            ) * 10000,
          ) / 10000,
        centered:
          Math.abs(applicationIdCenter - viewport.height / 2) <=
          Math.max(24, applicationIdBox.height / 2),
      },
    ],
  };
  if (capture) {
    result.values = {
      "Enterprise application": displayNameValue,
      "Application ID": applicationIdValue,
    };
  }
  return result;
};
