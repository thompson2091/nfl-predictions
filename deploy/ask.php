<?php
/**
 * Ask about a game — a thin proxy in front of the Anthropic API.
 *
 * THE BROWSER NEVER SEES THE KEY AND NEVER SUPPLIES THE CONTEXT.
 *
 * The page is static files, so a question answered from live data has to go
 * through something server-side. That something is a liability if it is built
 * carelessly: an endpoint that forwards whatever it is given, keyed to a
 * payment method, is a free general-purpose model for anyone who finds the
 * URL. Two rules keep it from being one.
 *
 *   1. The CONTEXT comes from a file on this server, chosen by a game id that
 *      is matched against the files that exist. Nothing the reader types
 *      becomes context, so the endpoint can only ever answer questions about
 *      this week's games.
 *   2. The RATE is capped per address and in total, in files under a
 *      directory only this script writes. The daily cap is the real
 *      protection — a per-IP limit alone is a limit per proxy.
 *
 * The key lives outside the web root and is never echoed, logged, or included
 * in an error. If it is missing the endpoint says it is unconfigured, which is
 * a fact about the server and gives nothing away.
 *
 * Written for PHP 5.5, which is what this host runs: no null coalescing, no
 * scalar type hints, no arrow functions.
 */

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

// ---------------------------------------------------------------- settings

$KEY_FILE   = '/etc/picksix/anthropic.key';   // outside the web root
$CTX_DIR    = __DIR__ . '/data/ask';          // one brief per game
$STATE_DIR  = '/var/lib/picksix';             // counters; not web readable
$MODEL      = 'claude-sonnet-4-5-20250929';
$MAX_TOKENS = 900;
$MAX_Q      = 400;        // characters; a question, not a document
$PER_IP_HR  = 15;
$PER_DAY    = 300;        // the cap that actually protects the bill
$TIMEOUT    = 45;

function fail($code, $msg) {
    http_response_code($code);
    echo json_encode(array('error' => $msg));
    exit;
}

// ---------------------------------------------------------------- input

if ($_SERVER['REQUEST_METHOD'] !== 'POST') fail(405, 'POST only');
$raw = file_get_contents('php://input');
if (strlen($raw) > 4000) fail(413, 'too long');
$in = json_decode($raw, true);
if (!is_array($in)) fail(400, 'expected JSON');

$game = isset($in['game']) ? (string)$in['game'] : '';
$q    = isset($in['q'])    ? trim((string)$in['q']) : '';

// A game id is two team codes and an underscore. Validated by SHAPE before it
// is ever used to build a path, so a traversal cannot be attempted at all.
if (!preg_match('/^[A-Z]{2,4}_[A-Z]{2,4}$/', $game)) fail(400, 'unknown game');
if ($q === '') fail(400, 'ask something');
if (mb_strlen($q) > $MAX_Q) fail(400, 'question too long');

$ctx_file = $CTX_DIR . '/' . $game . '.json';
if (!is_readable($ctx_file)) fail(404, 'no data for that game this week');

// ---------------------------------------------------------------- rate limit

function bump($dir, $name, $window, $limit) {
    if (!is_dir($dir)) @mkdir($dir, 0700, true);
    $path = $dir . '/' . $name;
    $now = time();
    $fh = @fopen($path, 'c+');
    if (!$fh) return true;              // cannot count: allow, do not break
    flock($fh, LOCK_EX);
    $body = stream_get_contents($fh);
    $rows = $body ? json_decode($body, true) : array();
    if (!is_array($rows)) $rows = array();
    $rows = array_values(array_filter($rows, function ($t) use ($now, $window) {
        return ($now - $t) < $window;
    }));
    $ok = count($rows) < $limit;
    if ($ok) $rows[] = $now;
    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, json_encode($rows));
    flock($fh, LOCK_UN);
    fclose($fh);
    return $ok;
}

$ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : 'unknown';
if (!bump($STATE_DIR, 'all.json', 86400, $PER_DAY)) {
    fail(429, 'the daily question budget is used up — try tomorrow');
}
if (!bump($STATE_DIR, 'ip-' . md5($ip) . '.json', 3600, $PER_IP_HR)) {
    fail(429, 'too many questions this hour — try again shortly');
}

// ---------------------------------------------------------------- key

if (!is_readable($KEY_FILE)) fail(503, 'the question service is not configured');
$key = trim(file_get_contents($KEY_FILE));
if ($key === '') fail(503, 'the question service is not configured');

// ---------------------------------------------------------------- call

$ctx = file_get_contents($ctx_file);

$system = "You answer questions about one NFL game for a betting site read by "
  . "people who do not bet much.\n\n"
  . "ANSWER ONLY FROM THE DATA BELOW, except that you may use web search for "
  . "news the data cannot contain — an injury reported today, a weather "
  . "forecast, a coaching change. Everything numeric must come from the data.\n\n"
  . "If the data does not answer the question, say so plainly and say what "
  . "would answer it. Never invent a number, a price or a player.\n\n"
  . "Rules: no betting advice, no 'lock' or 'guaranteed'. Explain what the "
  . "numbers mean and let the reader decide. Two short paragraphs at most. "
  . "Plain English; spell out any jargon you use.\n\n"
  . "A negative spread means the HOME team is favored.\n\n"
  // PLAYERS CHANGE TEAMS, AND THE MODEL'S MEMORY IS OLDER THAN THE DATA.
  // Asked which team a player is on, a model with no team in front of it
  // answers from training and sounds certain doing it. The rosters below are
  // ingested weekly and are the authority, so say which one wins.
  . "The teams, prices and projections below are THIS WEEK'S, ingested for "
  . "this game. Players change teams between seasons. If the data disagrees "
  . "with what you remember about a player's team, the data is right and "
  . "your memory is out of date — use the data and do not correct it.\n\n"
  . "THE DATA:\n" . $ctx;

$body = array(
    'model' => $MODEL,
    'max_tokens' => $MAX_TOKENS,
    'system' => $system,
    'tools' => array(array(
        'type' => 'web_search_20250305',
        'name' => 'web_search',
        'max_uses' => 3,
    )),
    'messages' => array(array('role' => 'user', 'content' => $q)),
);

$ch = curl_init('https://api.anthropic.com/v1/messages');
curl_setopt_array($ch, array(
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_TIMEOUT => $TIMEOUT,
    CURLOPT_POSTFIELDS => json_encode($body),
    CURLOPT_HTTPHEADER => array(
        'Content-Type: application/json',
        'x-api-key: ' . $key,
        'anthropic-version: 2023-06-01',
    ),
));
$resp = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err  = curl_error($ch);
curl_close($ch);

if ($resp === false) fail(502, 'could not reach the model (' . $err . ')');
if ($code !== 200) {
    // The upstream body is NOT returned: it can echo request details, and
    // this endpoint is public. The status is enough to act on.
    fail(502, 'the model returned ' . $code);
}

$out = json_decode($resp, true);
$text = '';
$searched = false;
if (isset($out['content']) && is_array($out['content'])) {
    foreach ($out['content'] as $block) {
        if (isset($block['type']) && $block['type'] === 'text') {
            $text .= $block['text'];
        }
        if (isset($block['type']) && strpos($block['type'], 'server_tool') === 0) {
            $searched = true;
        }
    }
}
if (trim($text) === '') fail(502, 'the model returned nothing');

echo json_encode(array('answer' => trim($text), 'searched' => $searched));
