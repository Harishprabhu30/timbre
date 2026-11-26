// Standalone macOS WKWebView host for the synthetic offline research page.
@import Cocoa;
@import WebKit;

static void fail(NSString *message) {
    fprintf(stderr, "%s\n", message.UTF8String);
    exit(EXIT_FAILURE);
}

static NSData *readFile(NSURL *url) {
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfURL:url options:0 error:&error];
    if (!data) fail(error.localizedDescription);
    return data;
}

static void writeFile(NSData *data, NSURL *url) {
    NSError *error = nil;
    if (!data || ![data writeToURL:url options:NSDataWritingAtomic error:&error]) {
        fail(error.localizedDescription ?: @"WebKit returned no audio data");
    }
}

@interface Runner : NSObject <WKNavigationDelegate>
@property(nonatomic, strong) WKWebView *view;
@property(nonatomic, strong) NSURL *directory;
@property(nonatomic, strong) NSArray<NSDictionary *> *cases;
@property(nonatomic) NSUInteger caseIndex;
- (void)startWithScript:(NSURL *)script;
@end

@implementation Runner

- (void)startWithScript:(NSURL *)script {
    NSString *source = [[NSString alloc] initWithData:readFile(script) encoding:NSUTF8StringEncoding];
    if (!source) fail(@"Research script must be UTF-8");

    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    [configuration.userContentController addUserScript:
        [[WKUserScript alloc] initWithSource:source injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    self.view = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 640, 480) configuration:configuration];
    self.view.navigationDelegate = self;
    [self.view loadHTMLString:@"<!doctype html><meta charset=utf-8><title>Timbre Legacy Research</title>" baseURL:nil];
}

- (void)webView:(WKWebView *)view didFinishNavigation:(WKNavigation *)navigation {
    [view evaluateJavaScript:@"navigator.userAgent" completionHandler:^(id value, NSError *error) {
        if (error) fail(error.localizedDescription);
        NSDictionary *environment = @{
            @"user_agent": value,
            @"webkit_bundle_version": [NSBundle bundleForClass:WKWebView.class].infoDictionary[@"CFBundleVersion"] ?: @"unknown",
            @"os_version": NSProcessInfo.processInfo.operatingSystemVersionString,
            @"audio_context": @"WKWebView OfflineAudioContext"
        };
        NSData *metadata = [NSJSONSerialization dataWithJSONObject:environment options:NSJSONWritingPrettyPrinted error:nil];
        writeFile(metadata, [self.directory URLByAppendingPathComponent:@"webkit.json"]);
        [self renderNext];
    }];
}

- (void)renderNext {
    if (self.caseIndex == self.cases.count) exit(EXIT_SUCCESS);
    NSDictionary *test = self.cases[self.caseIndex];
    NSURL *input = [self.directory URLByAppendingPathComponent:test[@"input"]];
    NSURL *output = [self.directory URLByAppendingPathComponent:test[@"output"]];
    NSDictionary *args = @{@"wav": [readFile(input) base64EncodedStringWithOptions:0], @"config": test[@"config"]};
    NSUInteger current = self.caseIndex;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (self.caseIndex == current) fail([NSString stringWithFormat:@"WebKit timed out rendering %@", test[@"output"]]);
    });
    [self.view callAsyncJavaScript:@"return await window.renderLegacyFixture(wav, config);" arguments:args
        inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value, NSError *error) {
            if (error) {
                fail([NSString stringWithFormat:@"%@: %@", test[@"output"], error.userInfo]);
            }
            NSData *audio = [[NSData alloc] initWithBase64EncodedString:value options:0];
            writeFile(audio, output);
            self.caseIndex++;
            [self renderNext];
        }];
}

- (void)webView:(WKWebView *)view didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    fail(error.localizedDescription);
}

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)view {
    fail(@"WKWebView content process terminated");
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) fail(@"Usage: webkit_runner <page-script.js> <manifest.json>");
        NSURL *script = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
        NSURL *manifest = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[2]]];
        NSError *error = nil;
        NSDictionary *plan = [NSJSONSerialization JSONObjectWithData:readFile(manifest) options:0 error:&error];
        if (error || ![plan[@"cases"] count]) fail(error.localizedDescription ?: @"No render cases");

        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyProhibited];
        Runner *runner = [Runner new];
        runner.directory = [manifest URLByDeletingLastPathComponent];
        runner.cases = plan[@"cases"];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if (!runner.caseIndex) fail(@"WKWebView did not complete its first render. Check macOS WebKit service access.");
        });
        [runner startWithScript:script];
        [application run];
    }
    return EXIT_FAILURE;
}
