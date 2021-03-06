/*
 *  Copyright (c) 2017-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#pragma once

#include "eden/fs/utils/UnboundedQueueThreadPool.h"

namespace facebook {
namespace eden {

// The Eden CPU thread pool is intended for miscellaneous background tasks.
class EdenCPUThreadPool : public UnboundedQueueThreadPool {
 public:
  explicit EdenCPUThreadPool();
};

} // namespace eden
} // namespace facebook
